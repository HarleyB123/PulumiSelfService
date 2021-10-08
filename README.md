# Pulumi Self Service at KPMG

This is a repo for the blog you can read about [here](https://medium.com/kpmg-uk-engineering/the-progression-of-self-service-at-kpmg-part-1-8923e64966e4).

Code by [msaldra](https://github.com/msaldra)

Blog by [HarleyB123](https://github.com/HarleyB123)

# Python - Secure Static Website Using Amazon S3, CloudFront, Route53, and Certificate Manager

Heavily based off of the [Pulumi provided example](https://github.com/pulumi/examples/tree/master/aws-py-static-website)! 

## What is included?

* S3 bucket configured to host static site
* CloudFront distribution pointing to S3 (takes ~20/30mins to propogate)
* logging bucket & config for CloudFront & S3
* ACM Cert & validation
* R53 records
* CloudFront Security Policy `TLSv1.2_2021`

## What else do I need?

* A domain
* This repo to be parameterised & tidied properly

## Deploying and running 

1. Install requirements:
    ```bash
    $ pip3 install -r requirements.txt
    ```

1. Setup your backed:
    ```bash
    $ pulumi login s3://pulumi-play
    ```

1. Create a new stack (once authed to AWS):

    ```bash
    $ pulumi stack init <stack_name>
    ```

1. Set the AWS region:

    ```bash
    $ pulumi config set aws:region eu-west-1
    ```

1. (For existing stacks/projects) Refresh Pulumi to update CloudFront & ACM config:

    ```bash
    $ pulumi refresh
    ```

1. Run `pulumi up` to preview and deploy changes.  After the preview is shown you will be
    prompted if you want to continue or not.

    ```bash
    $ pulumi up
    Previewing update (example):
        Type                              Name                                      Plan
    +   pulumi:pulumi:Stack               static-website-example                    create
    +   ├─ pulumi:providers:aws           east                                      create
    +   ├─ aws:s3:Bucket                  requestLogs                               create
    +   ├─ aws:s3:Bucket                  contentBucket                             create
    +   ├─ aws:acm:Certificate            certificate                               create
    +   ├─ aws:route53:Record             ***-validation                            create
    +   ├─ aws:acm:CertificateValidation  certificateValidation                     create
    +   ├─ aws:cloudfront:Distribution    cdn                                       create
    +   └─ aws:route53:Record             ***                                       create
    ```

1. To see the resources that were created, run `pulumi stack output`:

    ```bash
    $ pulumi stack output
    Current stack outputs (2):
        OUTPUT                           VALUE
        cloudfront_domain                ***.cloudfront.net
        content_bucket_url               s3://***
        content_bucket_website_endpoint  ***.s3-website-us-west-2.amazonaws.com
        target_domain_endpoint           https://***/
    ```

1. Open a browser to the target domain endpoint from above to see your beautiful static website. (May take a good few mins for Cloudfront to get sorted)

## Changes over Pulumi Example

* Use of `tldextract` over Python code in the Pulumi example that didn't cover all eventualities.
* Some sensible tagging changes & policy compliance tag. e.g. `allow_public` 
* CloudFront Security Policy `TLSv1.2_2019` 
* Bucket tweaks:
    * Versioning
    * Logs
    * Encryption
* Decoupled Static content from Pulumi repo - Allowing developers to manage their content seperately
