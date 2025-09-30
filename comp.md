You're absolutely correct - I apologize for the confusion. Let me provide the corrected explanation using the proper terminology: **Lakebase** (not lakehouse).

# Databricks Online Table Migration: Logical Explanation and Comparison

## Migration Overview

Databricks online tables (legacy) are deprecated and will be inaccessible after **January 15, 2026**. Organizations must migrate to one of two solutions: **Online Feature Store** or **Lakebase Synced Tables**. The choice depends on your specific use case, with Online Feature Store being the recommended approach for feature serving workloads.[1][2]

## Migration Path 1: Online Table to Online Feature Store

### Architecture
Online Feature Store is powered by **Lakebase** and designed specifically for **machine learning feature serving**. It provides high-performance, scalable access to feature data for real-time applications and model endpoints. The architecture uses capacity units (CU_1, CU_2, CU_4, CU_8) where each unit provides approximately 16GB of RAM with associated CPU and local SSD resources.[3]

### Migration Process
The migration involves three straightforward steps:[2][1]
1. Create an online feature store and publish feature tables
2. Update endpoints that depend on these online features (no input changes required for API/SDK)
3. Clean up legacy online tables after verification

## Migration Path 2: Online Table to Lakebase Synced Tables

### Architecture
**Lakebase Synced Tables** create **Unity Catalog read-only PostgreSQL tables** that automatically synchronize data from Unity Catalog tables to **Lakebase database instances**. This solution is designed for **OLTP (Online Transaction Processing)** workloads rather than feature serving.[4][1]

### Migration Process
The process requires additional infrastructure setup:[1][2]
1. Create a **Lakebase database instance** for storing synced tables
2. Optionally create a database catalog for Unity Catalog privileges
3. Create synced tables from source tables of online tables
4. Clean up legacy online tables

## Comparison Analysis

### A. Migration Complexity

**Online Feature Store (Easier Migration)**:[2][1]
- **Minimal infrastructure changes**: Uses existing feature table structure
- **No endpoint reconfiguration**: API calls remain unchanged
- **Direct migration path**: Three simple steps with built-in verification
- **Backward compatibility**: Seamless transition for ML workloads

**Lakebase Synced Tables (More Complex)**:[1][2]
- **Additional infrastructure required**: Must create new **Lakebase database instances**
- **Multi-step setup**: Database instance creation, catalog configuration, table creation
- **PostgreSQL knowledge needed**: Requires understanding of Postgres operations
- **More migration touchpoints**: Multiple systems to configure and test

### B. Cost Perspective

**Online Feature Store Pricing**:[5][3]
- **Capacity-based pricing**: CU_1, CU_2, CU_4, CU_8 tiers with linear scaling
- **Usage-based billing**: Pay for actual capacity and storage consumed
- **Storage costs**: Uses Databricks internal storage (not customer cloud storage)[5]
- **No explicit data refresh charges**: Built into capacity pricing[5]
- **Optimized for ML workloads**: Cost-effective for feature serving use cases

**Lakebase Synced Tables Pricing**:[6][4]
- **Database instance costs**: Must provision and pay for **Lakebase database instances**
- **Storage limitations**: 2TB total logical data size limit per instance[7][4]
- **Connection overhead**: Up to 16 database connections per table synchronization[4]
- **Postgres infrastructure**: Additional costs for managed PostgreSQL capabilities
- **Pipeline costs**: Lakeflow Declarative Pipelines for synchronization[4]

### C. Limitations and Performance

**Online Feature Store Limitations**:[3]
- **Regional availability**: Currently in public preview in specific regions only[3]
- **Capacity scaling**: Must choose appropriate CU level upfront
- **ML-focused**: Optimized specifically for feature serving, not general OLTP
- **Databricks ecosystem dependency**: Tight integration with Databricks ML workflows

**Lakebase Synced Tables Limitations**:[6][7][4]
- **2TB size limit**: Total logical data across all tables in instance cannot exceed 2TB[7][4]
- **1TB recommended limit**: For tables requiring refreshes rather than recreation[4]
- **20 synced tables maximum**: Per source table limit[4]
- **Read-only constraints**: Tables are read-only in Postgres for data integrity[4]
- **1000 concurrent connections**: Maximum per **Lakebase database instance**[6]
- **Workspace scoping**: Database instances limited to single workspace[6]
- **Double storage during refresh**: Temporary doubling of storage during full refreshes[4]

**Performance Characteristics**:

**Online Feature Store**:[3]
- **Low-latency access**: Optimized for real-time feature retrieval
- **Auto-scaling throughput**: Scales with request load automatically[5]
- **ML-optimized**: Built specifically for model serving performance
- **Read replicas**: Support for distributed read traffic[8]

**Lakebase Synced Tables**:[4]
- **PostgreSQL performance**: Standard Postgres query performance
- **Sync latency**: Depends on Lakeflow pipeline efficiency
- **Join capabilities**: Supports query-time joins with other Postgres tables[4]
- **OLTP optimized**: Better for transactional workloads than feature serving

## Recommendation Logic

**Choose Online Feature Store when**:
- Primary use case is ML feature serving
- Need low-latency feature access for model inference
- Want simplified migration with minimal infrastructure changes
- Require auto-scaling capabilities for varying loads
- Working within supported regions

**Choose Lakebase Synced Tables when**:
- Need OLTP capabilities beyond feature serving
- Require PostgreSQL-specific functionality
- Need query-time joins across multiple tables
- Have existing PostgreSQL expertise and tooling
- Data size remains within 2TB limits per instance
- Willing to manage additional **Lakebase database infrastructure**

The **Online Feature Store migration path offers significantly easier implementation with lower operational complexity**, making it the logical choice for most ML-focused organizations, while **Lakebase Synced Tables** provide broader database capabilities at the cost of increased complexity and infrastructure overhead.[2][1]

[1](https://learn.microsoft.com/en-us/azure/databricks/machine-learning/feature-store/migrate-from-online-tables)
[2](https://docs.databricks.com/aws/en/machine-learning/feature-store/migrate-from-online-tables)
[3](https://learn.microsoft.com/en-us/azure/databricks/machine-learning/feature-store/online-feature-store)
[4](https://docs.databricks.com/aws/en/oltp/instances/sync-data/sync-table)
[5](https://community.databricks.com/t5/machine-learning/online-feature-table-storage/td-p/102328)
[6](https://docs.databricks.com/aws/en/oltp/instances/instance)
[7](https://learn.microsoft.com/en-us/azure/databricks/oltp/instances/sync-data/sync-table)
[8](https://docs.databricks.com/aws/en/machine-learning/feature-store/online-feature-store)
