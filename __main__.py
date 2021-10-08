import json
import mimetypes
import os
import tldextract

from pulumi import (
    export,
    FileAsset,
    ResourceOptions,
    Config,
    Output,
    get_project,
    get_stack,
)
import pulumi_aws
import pulumi_aws.acm
import pulumi_aws.cloudfront
import pulumi_aws.config
import pulumi_aws.route53
import pulumi_aws.s3


# Read the configuration for this stack.
stack_config = Config()
target_domain = stack_config.require("targetDomain")
certificate_arn = stack_config.get("certificateArn")

# Create a logs bucket logs
logs_bucket = pulumi_aws.s3.Bucket(
    "requestLogs",
    bucket=f"{target_domain}-logs",
    acl="log-delivery-write",
    versioning=pulumi_aws.s3.BucketVersioningArgs(
        enabled=True,
    ),
    server_side_encryption_configuration=pulumi_aws.s3.BucketServerSideEncryptionConfigurationArgs(
        rule=pulumi_aws.s3.BucketServerSideEncryptionConfigurationRuleArgs(
            apply_server_side_encryption_by_default=pulumi_aws.s3.BucketServerSideEncryptionConfigurationRuleApplyServerSideEncryptionByDefaultArgs(
                sse_algorithm="AES256",
            ),
        ),
    ),
    tags={"project": get_project(), "stack": get_stack()},
)

# Create an S3 bucket configured as a website bucket.
content_bucket = pulumi_aws.s3.Bucket(
    "contentBucket",
    bucket=target_domain,
    acl="public-read",
    website=pulumi_aws.s3.BucketWebsiteArgs(
        index_document="index.html", error_document="404.html"
    ),
    loggings=[
        pulumi_aws.s3.BucketLoggingArgs(
            target_bucket=logs_bucket.id,
            target_prefix=f"${target_domain}/s3",
        )
    ],
    versioning=pulumi_aws.s3.BucketVersioningArgs(
        enabled=True,
    ),
    server_side_encryption_configuration=pulumi_aws.s3.BucketServerSideEncryptionConfigurationArgs(
        rule=pulumi_aws.s3.BucketServerSideEncryptionConfigurationRuleArgs(
            apply_server_side_encryption_by_default=pulumi_aws.s3.BucketServerSideEncryptionConfigurationRuleApplyServerSideEncryptionByDefaultArgs(
                sse_algorithm="AES256",
            ),
        ),
    ),
    tags={"allow_public": "true", "project": get_project(), "stack": get_stack()},
)

TEN_MINUTES = 60 * 10

# Provision a certificate if the arn is not provided via configuration.
if certificate_arn is None:
    # CloudFront is in us-east-1 and expects the ACM certificate to also be in us-east-1.
    # So, we create an east_region provider specifically for these operations.
    east_region = pulumi_aws.Provider(
        "east", profile=pulumi_aws.config.profile, region="us-east-1"
    )

    # Get a certificate for our website domain name.
    certificate = pulumi_aws.acm.Certificate(
        "certificate",
        domain_name=target_domain,
        validation_method="DNS",
        opts=ResourceOptions(provider=east_region),
    )

    # Find the Route 53 hosted zone so we can create the validation record.
    ext = tldextract.extract(target_domain)
    subdomain = ext.subdomain
    parent_domain = ext.registered_domain

    # This assume R53 already exsits
    hzid = pulumi_aws.route53.get_zone(name=parent_domain).id

    # Create a validation record to prove that we own the domain.
    cert_validation_domain = pulumi_aws.route53.Record(
        f"{target_domain}-validation",
        name=certificate.domain_validation_options.apply(
            lambda o: o[0].resource_record_name
        ),
        zone_id=hzid,
        type=certificate.domain_validation_options.apply(
            lambda o: o[0].resource_record_type
        ),
        records=[
            certificate.domain_validation_options.apply(
                lambda o: o[0].resource_record_value
            )
        ],
        ttl=TEN_MINUTES,
    )

    # Create a special resource to await complete validation of the cert.
    # Note that this is not a real AWS resource.
    cert_validation = pulumi_aws.acm.CertificateValidation(
        "certificateValidation",
        certificate_arn=certificate.arn,
        validation_record_fqdns=[cert_validation_domain.fqdn],
        opts=ResourceOptions(provider=east_region),
    )

    certificate_arn = cert_validation.certificate_arn

# Create the CloudFront distribution
cdn = pulumi_aws.cloudfront.Distribution(
    "cdn",
    enabled=True,
    aliases=[target_domain],
    origins=[
        pulumi_aws.cloudfront.DistributionOriginArgs(
            origin_id=content_bucket.arn,
            domain_name=content_bucket.website_endpoint,
            custom_origin_config=pulumi_aws.cloudfront.DistributionOriginCustomOriginConfigArgs(
                origin_protocol_policy="http-only",
                http_port=80,
                https_port=443,
                origin_ssl_protocols=["TLSv1.2"],
            ),
        )
    ],
    default_root_object="index.html",
    default_cache_behavior=pulumi_aws.cloudfront.DistributionDefaultCacheBehaviorArgs(
        target_origin_id=content_bucket.arn,
        viewer_protocol_policy="redirect-to-https",
        allowed_methods=["GET", "HEAD", "OPTIONS"],
        cached_methods=["GET", "HEAD", "OPTIONS"],
        forwarded_values=pulumi_aws.cloudfront.DistributionDefaultCacheBehaviorForwardedValuesArgs(
            cookies=pulumi_aws.cloudfront.DistributionDefaultCacheBehaviorForwardedValuesCookiesArgs(
                forward="none"
            ),
            query_string=False,
        ),
        min_ttl=0,
        default_ttl=TEN_MINUTES,
        max_ttl=TEN_MINUTES,
    ),
    # PriceClass_100 is the lowest cost tier (US/EU only).
    price_class="PriceClass_100",
    custom_error_responses=[
        pulumi_aws.cloudfront.DistributionCustomErrorResponseArgs(
            error_code=404, response_code=404, response_page_path="/404.html"
        )
    ],
    # Use the certificate we generated for this distribution.
    viewer_certificate=pulumi_aws.cloudfront.DistributionViewerCertificateArgs(
        acm_certificate_arn=certificate_arn,
        ssl_support_method="sni-only",
        minimum_protocol_version="TLSv1.2_2021",
    ),
    restrictions=pulumi_aws.cloudfront.DistributionRestrictionsArgs(
        geo_restriction=pulumi_aws.cloudfront.DistributionRestrictionsGeoRestrictionArgs(
            restriction_type="none"
        )
    ),
    # Put access logs in the log bucket we created earlier.
    logging_config=pulumi_aws.cloudfront.DistributionLoggingConfigArgs(
        bucket=logs_bucket.bucket_domain_name,
        include_cookies=False,
        prefix=f"${target_domain}/cloudfront",
    ),
    # CloudFront typically takes 15 minutes to fully deploy a new distribution.
    # Skip waiting for that to complete.
    wait_for_deployment=False,
)


def create_alias_record(target_domain, distribution):
    """
    Create a Route 53 Alias A record from the target domain name to the CloudFront distribution.
    """
    ext = tldextract.extract(target_domain)
    subdomain = ext.subdomain
    parent_domain = ext.registered_domain

    hzid = pulumi_aws.route53.get_zone(name=parent_domain).id
    return pulumi_aws.route53.Record(
        target_domain,
        name=subdomain,
        zone_id=hzid,
        type="A",
        aliases=[
            pulumi_aws.route53.RecordAliasArgs(
                name=distribution.domain_name,
                zone_id=distribution.hosted_zone_id,
                evaluate_target_health=True,
            )
        ],
    )


alias_a_record = create_alias_record(target_domain, cdn)

# Export the bucket URL, bucket website endpoint, and the CloudFront distribution information.
export("content_bucket_url", Output.concat("s3://", content_bucket.bucket))
export("content_bucket_website_endpoint", content_bucket.website_endpoint)
export("cloudfront_domain", cdn.domain_name)
export("target_domain_endpoint", f"https://{target_domain}/")
