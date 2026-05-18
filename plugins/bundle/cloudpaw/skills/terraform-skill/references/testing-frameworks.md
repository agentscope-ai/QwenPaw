# Testing Frameworks - Detailed Guide

> **Part of:** [terraform-skill](../SKILL.md)
> **Purpose:** Detailed guides for Terraform/OpenTofu testing frameworks

This document provides in-depth guidance on testing frameworks for Infrastructure as Code. For the decision matrix and high-level overview, see the [main skill file](../SKILL.md#testing-strategy-framework).

---

## Table of Contents

1. [Static Analysis](#static-analysis)
2. [Plan Testing](#plan-testing)
3. [Native Terraform Tests](#native-terraform-tests)
4. [Terratest (Go-based)](#terratest-go-based)

---

## Static Analysis

**Always do this first.** Zero cost, catches 40%+ of issues before deployment.

### Pre-commit Hooks

```yaml
# In .pre-commit-config.yaml
- repo: https://github.com/antonbabenko/pre-commit-terraform
  hooks:
    - id: terraform_fmt
    - id: terraform_validate
    - id: terraform_tflint
```

### What Each Tool Checks

- **`terraform fmt`** - Code formatting consistency
- **`terraform validate`** - Syntax and internal consistency
- **`TFLint`** - Best practices, provider-specific rules
- **`trivy` / `checkov`** - Security vulnerabilities

### When to Use

Every commit, always. Zero cost, catches 40%+ of issues.

---

## Plan Testing

### What terraform plan Validates

- Verify expected resources will be created/modified/destroyed
- Catch provider authentication issues
- Validate variable combinations
- Review before applying

### In CI/CD

```bash
terraform init
terraform plan -out=tfplan

# Optionally: Convert plan to JSON and validate with tools
terraform show -json tfplan | jq '.'
```

### Limitations

- Doesn't deploy real infrastructure
- Can't catch runtime issues (IAM permissions, network connectivity)
- Won't find resource-specific bugs

---

## Native Terraform Tests

**Available:** Terraform 1.6+, OpenTofu 1.6+

### When to Use

- Team primarily works in HCL (no Go/Ruby experience needed)
- Testing logical operations and module behavior
- Want to avoid external testing dependencies

### Basic Structure

```hcl
# tests/s3_bucket.tftest.hcl
run "create_bucket" {
  command = apply

  assert {
    condition     = aws_s3_bucket.main.bucket != ""
    error_message = "S3 bucket name must be set"
  }
}

run "verify_encryption" {
  command = plan

  assert {
    condition     = aws_s3_bucket_server_side_encryption_configuration.main.rule[0].apply_server_side_encryption_by_default[0].sse_algorithm == "AES256"
    error_message = "Bucket must use AES256 encryption"
  }
}
```

### Critical: Validate Resource Schemas First

**Always use Terraform MCP to validate resource schemas before writing tests:**

```bash
# Example workflow in Claude Code:
# 1. Search for provider documentation
mcp__terraform__search_providers({
  provider_name: "aws",
  provider_namespace: "hashicorp",
  service_slug: "s3_bucket_server_side_encryption_configuration",
  provider_document_type: "resources"
})

# 2. Get detailed schema
mcp__terraform__get_provider_details({
  provider_doc_id: "12345"  # from search results
})
```

**Why This Matters:**
- Some blocks are **sets** (unordered, no indexing with `[0]`)
- Some blocks are **lists** (ordered, indexable)
- Some attributes are **computed** (only known after apply)

**Common Schema Patterns:**

| AWS Resource | Block Type | Indexing |
|--------------|------------|----------|
| `rule` in `aws_s3_bucket_server_side_encryption_configuration` | **set** | ❌ Cannot use `[0]` |
| `transition` in `aws_s3_bucket_lifecycle_configuration` | **set** | ❌ Cannot use `[0]` |
| `noncurrent_version_expiration` in lifecycle | **list** | ✅ Can use `[0]` |

### Working with Set-Type Blocks

**Problem:** Cannot index sets with `[0]`
```hcl
# ❌ WRONG: This will fail
condition = aws_s3_bucket_server_side_encryption_configuration.this.rule[0].bucket_key_enabled == true
# Error: Cannot index a set value
```

**Solution 1:** Use `command = apply` to materialize the set
```hcl
run "test_encryption" {
  command = apply  # Creates real/mocked resources

  assert {
    # Now the set is materialized and can be checked
    condition     = length([for rule in aws_s3_bucket_server_side_encryption_configuration.this.rule :
                             rule.bucket_key_enabled if rule.bucket_key_enabled == true]) > 0
    error_message = "Bucket key should be enabled"
  }
}
```

**Solution 2:** Check at resource level (avoid accessing nested blocks)
```hcl
run "test_encryption_exists" {
  command = plan

  assert {
    # Check that the resource exists without accessing set members
    condition     = aws_s3_bucket_server_side_encryption_configuration.this != null
    error_message = "Encryption configuration should be created"
  }
}
```

**Solution 3:** Use for expressions (works in apply mode)
```hcl
run "test_encryption_algorithm" {
  command = apply

  assert {
    condition     = alltrue([
      for rule in aws_s3_bucket_server_side_encryption_configuration.this.rule :
      alltrue([
        for config in rule.apply_server_side_encryption_by_default :
        config.sse_algorithm == "AES256"
      ])
    ])
    error_message = "Encryption should use AES256"
  }
}
```

### command = plan vs command = apply

**Critical decision:** When to use each command mode

#### Use `command = plan`

**When:**
- Checking input validation
- Verifying resource will be created
- Testing variable defaults
- Checking resource attributes that are **input-derived** (not computed)

**Example:**
```hcl
run "test_input_validation" {
  command = plan  # Fast, no resource creation

  variables {
    bucket = "test-bucket"
  }

  assert {
    # bucket name is an input, known at plan time
    condition     = aws_s3_bucket.this.bucket == "test-bucket"
    error_message = "Bucket name should match input"
  }
}
```

#### Use `command = apply`

**When:**
- Checking computed attributes (IDs, ARNs, generated names)
- Accessing set-type blocks
- Verifying actual resource behavior
- Testing with real/mocked provider responses

**Example:**
```hcl
run "test_computed_values" {
  command = apply  # Executes and gets computed values

  variables {
    bucket_prefix = "test-"  # AWS generates full name
  }

  assert {
    # bucket name is computed from prefix, only known after apply
    condition     = length(aws_s3_bucket.this.bucket) > 0
    error_message = "Bucket should have generated name"
  }
}
```

#### Common Pitfall: Checking Computed Values in Plan Mode

**Problem:**
```hcl
run "test_bucket_prefix" {
  command = plan  # ❌ WRONG MODE

  variables {
    bucket_prefix = "test-prefix-"
  }

  assert {
    # bucket is computed from prefix, unknown at plan time!
    condition     = aws_s3_bucket.this.bucket == null
    error_message = "Bucket name should be null when using bucket_prefix"
  }
}
# Error: Condition expression could not be evaluated at this time
```

**Solution:**
```hcl
run "test_bucket_prefix" {
  command = apply  # ✅ CORRECT MODE or check differently

  variables {
    bucket_prefix = "test-prefix-"
  }

  assert {
    # Now bucket has been generated by provider
    condition     = startswith(aws_s3_bucket.this.bucket, "test-prefix-")
    error_message = "Bucket name should start with prefix"
  }
}
```

**Quick Decision Guide:**
```
Checking input values? → command = plan
Checking computed values? → command = apply
Accessing set-type blocks? → command = apply
Need fast feedback? → command = plan (with mocks)
Testing real behavior? → command = apply (without mocks)
```

### With Mocking (1.7+)

```hcl
mock_provider "aws" {
  mock_resource "aws_instance" {
    defaults = {
      id  = "i-mock123"
      arn = "arn:aws:ec2:us-east-1:123456789:instance/i-mock123"
    }
  }
}
```

### Pros

- Native HCL syntax (familiar to Terraform users)
- No external dependencies
- Fast execution with mocks
- Good for unit testing module logic

### Cons

- Newer feature (less mature than Terratest)
- Limited ecosystem/examples
- Mocking doesn't catch real-world AWS behavior

---

### Complete Test Examples (Following Best Practices)

#### Example 1: S3 Bucket Tests

```hcl
# tests/unit/s3_bucket.tftest.hcl

mock_provider "aws" {}  # Zero cost with mocks

# Test 1: Input validation (fast, plan mode)
run "validate_bucket_name" {
  command = plan

  variables {
    bucket = "my-test-bucket"
  }

  assert {
    condition     = aws_s3_bucket.this.bucket == "my-test-bucket"
    error_message = "Bucket name should match input"
  }
}

# Test 2: Encryption defaults (apply mode for set access)
run "verify_default_encryption" {
  command = apply

  variables {
    bucket = "encrypted-bucket"
  }

  assert {
    # Using for expression to check set-type block
    condition = alltrue([
      for rule in aws_s3_bucket_server_side_encryption_configuration.this.rule :
      alltrue([
        for config in rule.apply_server_side_encryption_by_default :
        config.sse_algorithm == "AES256"
      ])
    ])
    error_message = "Default encryption should be AES256"
  }

  assert {
    # Check bucket key at rule level
    condition = alltrue([
      for rule in aws_s3_bucket_server_side_encryption_configuration.this.rule :
      rule.bucket_key_enabled == true
    ])
    error_message = "Bucket key should be enabled"
  }
}

# Test 3: Computed values (apply mode required)
run "verify_generated_name" {
  command = apply

  variables {
    bucket_prefix = "test-"
  }

  assert {
    condition     = startswith(aws_s3_bucket.this.bucket, "test-")
    error_message = "Generated bucket name should have prefix"
  }

  assert {
    condition     = length(aws_s3_bucket.this.bucket) > 5
    error_message = "Bucket name should be generated"
  }
}
```

#### Example 2: Lifecycle Rules

```hcl
# tests/unit/lifecycle.tftest.hcl

mock_provider "aws" {}

run "verify_lifecycle_transitions" {
  command = apply  # Required for set-type transition blocks

  variables {
    bucket = "lifecycle-bucket"
    lifecycle_rules = [{
      id      = "archive"
      enabled = true
      transition = [
        { days = 90, storage_class = "GLACIER" },
        { days = 180, storage_class = "DEEP_ARCHIVE" }
      ]
    }]
  }

  assert {
    # Check that both transitions exist using for expression
    condition = length([
      for rule in aws_s3_bucket_lifecycle_configuration.this[0].rule :
      rule.id if rule.id == "archive"
    ]) == 1
    error_message = "Lifecycle rule should exist"
  }

  assert {
    # Verify transition count using length
    condition = alltrue([
      for rule in aws_s3_bucket_lifecycle_configuration.this[0].rule :
      length(rule.transition) == 2
    ])
    error_message = "Should have 2 transitions"
  }
}
```

---

## Terratest (Go-based)

**Recommended for:** Teams with Go experience, robust integration testing

### When to Use

- Team has Go experience
- Need robust integration testing
- Testing multiple providers/complex infrastructure
- Want battle-tested framework with large community

### Basic Structure

```go
package test

import (
    "testing"
    "github.com/gruntwork-io/terratest/modules/terraform"
    "github.com/stretchr/testify/assert"
)

func TestS3Module(t *testing.T) {
    t.Parallel() // ALWAYS include for parallel execution

    terraformOptions := &terraform.Options{
        TerraformDir: "../examples/complete",
        Vars: map[string]interface{}{
            "bucket_name": "test-bucket-" + uniqueId(),
        },
    }

    // Clean up resources after test
    defer terraform.Destroy(t, terraformOptions)

    // Run terraform init and apply
    terraform.InitAndApply(t, terraformOptions)

    // Get outputs and verify
    bucketName := terraform.Output(t, terraformOptions, "bucket_name")
    assert.NotEmpty(t, bucketName)
}
```

### Cost Management

```go
// Use tags for automated cleanup
Vars: map[string]interface{}{
    "tags": map[string]string{
        "Environment": "test",
        "TTL":         "2h", // Auto-delete after 2 hours
    },
}
```

### Critical Patterns

1. **Always use `t.Parallel()`** - Enables parallel test execution
2. **Always use `defer terraform.Destroy()`** - Ensures cleanup
3. **Use unique identifiers** - Avoid resource conflicts
4. **Tag resources** - Enable cost tracking and automated cleanup
5. **Use separate AWS accounts** - Isolate test infrastructure

### Real-world Costs

- Small module (S3, IAM): $0-5 per run
- Medium module (VPC, EC2): $5-20 per run
- Large module (RDS, ECS cluster): $20-100 per run

### Optimization with Test Stages

```go
// Test stages for faster iteration
stage := test_structure.RunTestStage

stage(t, "setup", func() {
    terraform.InitAndApply(t, opts)
})

stage(t, "validate", func() {
    // Assertions here
})

stage(t, "teardown", func() {
    terraform.Destroy(t, opts)
})

// Skip stages during development:
// export SKIP_setup=true
// export SKIP_teardown=true
```

---

## Best Practices Summary

### For All Frameworks

1. **Start with static analysis** - Always free, always fast
2. **Use unique identifiers** - Prevent resource conflicts
3. **Tag test resources** - Enable tracking and cleanup
4. **Separate test accounts** - Isolate test infrastructure
5. **Implement TTL** - Automatic resource cleanup

### Framework Selection

```
Quick syntax check? → terraform validate + fmt
Security scan? → trivy + checkov
Terraform 1.6+, simple logic? → Native tests
Pre-1.6, or complex integration? → Terratest
```

### Cost Optimization

1. Use mocking for unit tests
2. Implement resource TTL tags
3. Run integration tests only on main branch
4. Use smaller instance types in tests
5. Share test resources when safe

---

**Back to:** [Main Skill File](../SKILL.md)
