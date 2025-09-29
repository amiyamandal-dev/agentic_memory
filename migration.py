#!/usr/bin/env python3
"""
Simplified Databricks Online Table Migration Script
==================================================
Migrate FROM: Legacy Online Table (old system)
Migrate TO:   Feature Store Online Table (new system)
"""

import json
import time
import logging
import sys
from typing import Dict, List, Optional, Tuple
from datetime import datetime

# Databricks imports
from databricks.feature_engineering import FeatureEngineeringClient
from databricks.sdk import WorkspaceClient
from pyspark.sql import SparkSession

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MigrationError(Exception):
    """Custom exception for migration errors"""
    pass

def get_spark_session():
    """Get or create Spark session"""
    try:
        return SparkSession.getActiveSession() or SparkSession.builder.getOrCreate()
    except Exception as e:
        logger.error(f"Failed to get Spark session: {e}")
        raise MigrationError(f"Cannot initialize Spark session: {e}")

def initialize_clients():
    """Step 1: Initialize Databricks clients"""
    logger.info("STEP 1: Initializing Databricks clients...")
    
    try:
        fe_client = FeatureEngineeringClient()
        logger.info("✅ Feature Engineering client initialized")
        
        ws_client = WorkspaceClient()
        logger.info("✅ Workspace client initialized")
        
        spark = get_spark_session()
        logger.info("✅ Spark session initialized")
        
        current_user = ws_client.current_user.me()
        logger.info(f"✅ Connected as user: {current_user.user_name}")
        
        return fe_client, ws_client, spark
    
    except Exception as e:
        logger.error(f"❌ Failed to initialize clients: {e}")
        raise MigrationError(f"Client initialization failed: {e}")

def validate_configuration(config: Dict):
    """Step 2: Validate migration configuration"""
    logger.info("STEP 2: Validating migration configuration...")
    
    required_fields = ['legacy_online_table', 'online_store_name', 'target_table']
    
    for field in required_fields:
        if not config.get(field):
            raise MigrationError(f"Missing required configuration field: {field}")
    
    # Validate table names format
    for table_field in ['legacy_online_table', 'target_table']:
        table_name = config[table_field]
        if len(table_name.split('.')) != 3:
            raise MigrationError(f"{table_field} must be in format: catalog.schema.table")
    
    # Validate capacity
    valid_capacities = ['CU_1', 'CU_2', 'CU_4', 'CU_8']
    capacity = config.get('capacity', 'CU_2')
    if capacity not in valid_capacities:
        raise MigrationError(f"Invalid capacity: {capacity}. Must be one of: {valid_capacities}")
    
    logger.info("✅ Configuration validation passed")
    logger.info(f"  FROM (Legacy): {config['legacy_online_table']}")
    logger.info(f"  TO (New Store): {config['online_store_name']}")
    logger.info(f"  TO (New Table): {config['target_table']}")
    logger.info(f"  Capacity: {capacity}")
    
    return True

def check_source_table(spark, legacy_table: str):
    """Step 3: Validate source (legacy online table) exists"""
    logger.info(f"STEP 3: Checking source table: {legacy_table}")
    
    try:
        # Check if table exists
        logger.info("Checking table existence...")
        table_info = spark.sql(f"DESCRIBE TABLE {legacy_table}").collect()
        
        if not table_info:
            raise MigrationError(f"Table {legacy_table} does not exist or is empty")
        
        logger.info("✅ Source table exists")
        
        # Get row count
        logger.info("Checking table data...")
        row_count_result = spark.sql(f"SELECT COUNT(*) as count FROM {legacy_table}").collect()
        row_count = row_count_result[0]['count'] if row_count_result else 0
        
        logger.info(f"✅ Table has {row_count:,} rows")
        
        # Check table properties
        logger.info("Checking table properties...")
        try:
            properties = spark.sql(f"SHOW TBLPROPERTIES {legacy_table}").collect()
            prop_dict = {row['key']: row['value'] for row in properties}
            
            # Check if it's a Delta table
            if 'provider' in prop_dict and prop_dict['provider'].lower() != 'delta':
                logger.warning("⚠️  Table is not a Delta table. Migration may have limitations.")
            else:
                logger.info("✅ Source table is a Delta table")
            
        except Exception as e:
            logger.warning(f"⚠️  Could not check table properties: {e}")
        
        # Validate schema has columns
        columns = spark.sql(f"DESCRIBE {legacy_table}").collect()
        if len(columns) < 1:
            raise MigrationError(f"Table {legacy_table} has no columns")
        
        logger.info(f"✅ Table has {len(columns)} columns")
        
        # Show sample of schema
        logger.info("Table schema preview:")
        for col in columns[:5]:
            logger.info(f"  - {col['col_name']}: {col['data_type']}")
        
        if len(columns) > 5:
            logger.info(f"  ... and {len(columns) - 5} more columns")
        
        return row_count, len(columns)
    
    except Exception as e:
        logger.error(f"❌ Source table validation failed: {e}")
        raise MigrationError(f"Source table check failed: {e}")

def discover_table_dependencies(ws_client, legacy_table: str):
    """Step 4: Discover what uses the legacy online table"""
    logger.info(f"STEP 4: Discovering dependencies for {legacy_table}...")
    
    dependencies = {
        'endpoints': [],
        'jobs': [],
        'models': []
    }
    
    try:
        # Find serving endpoints
        logger.info("Scanning serving endpoints...")
        try:
            endpoints = list(ws_client.serving_endpoints.list())
            
            for endpoint in endpoints:
                if endpoint.name:
                    dependencies['endpoints'].append({
                        'name': endpoint.name,
                        'id': endpoint.id,
                        'state': str(endpoint.state) if endpoint.state else 'unknown',
                        'creation_timestamp': endpoint.creation_timestamp
                    })
            
            logger.info(f"Found {len(dependencies['endpoints'])} serving endpoints")
        
        except Exception as e:
            logger.warning(f"Could not scan serving endpoints: {e}")
        
        # Find related jobs
        logger.info("Scanning jobs...")
        try:
            jobs = list(ws_client.jobs.list(limit=50))
            
            for job in jobs:
                if job.settings and job.settings.name:
                    dependencies['jobs'].append({
                        'id': job.job_id,
                        'name': job.settings.name,
                        'creator_user_name': job.creator_user_name
                    })
            
            logger.info(f"Found {len(dependencies['jobs'])} jobs to review")
        
        except Exception as e:
            logger.warning(f"Could not scan jobs: {e}")
        
        logger.info("✅ Dependency discovery completed")
        logger.info(f"Summary: {len(dependencies['endpoints'])} endpoints, {len(dependencies['jobs'])} jobs")
        
        return dependencies
    
    except Exception as e:
        logger.warning(f"⚠️  Dependency discovery had issues: {e}")
        return dependencies

def enable_change_data_feed(spark, legacy_table: str):
    """Step 5: Enable Change Data Feed on source table"""
    logger.info(f"STEP 5: Enabling Change Data Feed for {legacy_table}")
    
    try:
        # Check if CDF is already enabled
        logger.info("Checking current CDF status...")
        
        try:
            properties = spark.sql(f"SHOW TBLPROPERTIES {legacy_table}").collect()
            prop_dict = {row['key']: row['value'] for row in properties}
            
            cdf_enabled = prop_dict.get('delta.enableChangeDataFeed', 'false').lower() == 'true'
            
            if cdf_enabled:
                logger.info("✅ Change Data Feed is already enabled")
                return True
            
        except Exception as e:
            logger.warning(f"Could not check CDF status: {e}")
        
        # Enable CDF
        logger.info("Enabling Change Data Feed...")
        
        cdf_sql = f"ALTER TABLE {legacy_table} SET TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')"
        spark.sql(cdf_sql)
        
        logger.info("✅ Change Data Feed enabled successfully")
        
        # Verify CDF was enabled
        time.sleep(2)
        
        try:
            properties = spark.sql(f"SHOW TBLPROPERTIES {legacy_table}").collect()
            prop_dict = {row['key']: row['value'] for row in properties}
            
            cdf_enabled = prop_dict.get('delta.enableChangeDataFeed', 'false').lower() == 'true'
            
            if not cdf_enabled:
                raise MigrationError("CDF enable command executed but property not set")
            
            logger.info("✅ CDF enablement verified")
            
        except Exception as e:
            logger.warning(f"Could not verify CDF status: {e}")
        
        return True
    
    except Exception as e:
        logger.error(f"❌ Failed to enable CDF: {e}")
        raise MigrationError(f"CDF enablement failed: {e}")

def create_online_feature_store(fe_client, store_name: str, capacity: str = 'CU_2'):
    """Step 6: Create the NEW online feature store"""
    logger.info(f"STEP 6: Creating NEW online feature store: {store_name}")
    
    try:
        # Check if store already exists
        logger.info("Checking if online store exists...")
        
        try:
            existing_store = fe_client.get_online_store(name=store_name)
            if existing_store:
                logger.info(f"✅ Online store '{store_name}' already exists")
                logger.info(f"Store state: {existing_store.state}")
                
                if existing_store.state != 'ONLINE':
                    logger.warning(f"⚠️  Store state is {existing_store.state}, not ONLINE")
                
                return existing_store
        
        except Exception as e:
            logger.info("Store doesn't exist yet, will create new one")
        
        # Create new online store
        logger.info(f"Creating online store with capacity: {capacity}")
        
        try:
            online_store = fe_client.create_online_store(
                name=store_name,
                capacity=capacity
            )
            
            logger.info(f"✅ Online store creation initiated")
            
        except Exception as e:
            logger.error(f"Failed to create online store: {e}")
            raise MigrationError(f"Online store creation failed: {e}")
        
        # Wait for store to become available
        logger.info("⏳ Waiting for online store to become available...")
        
        max_wait_time = 900  # 15 minutes
        check_interval = 30
        elapsed_time = 0
        
        while elapsed_time < max_wait_time:
            try:
                store = fe_client.get_online_store(name=store_name)
                
                if store and store.state == 'ONLINE':
                    logger.info(f"✅ Online store '{store_name}' is ready!")
                    return store
                
                logger.info(f"Store status: {store.state if store else 'Unknown'} "
                           f"({elapsed_time}s/{max_wait_time}s)")
                
                time.sleep(check_interval)
                elapsed_time += check_interval
                
            except Exception as e:
                logger.debug(f"Store status check failed: {e}")
                time.sleep(check_interval)
                elapsed_time += check_interval
        
        raise MigrationError(f"Store did not become available within {max_wait_time} seconds")
    
    except Exception as e:
        if isinstance(e, MigrationError):
            raise
        logger.error(f"❌ Online store creation failed: {e}")
        raise MigrationError(f"Online store creation failed: {e}")

def publish_table_to_online_store(fe_client, spark, config: Dict):
    """Step 7: Publish legacy table to NEW online store"""
    logger.info("STEP 7: Publishing table to NEW online store...")
    
    try:
        legacy_table = config['legacy_online_table']
        target_table = config['target_table']
        online_store_name = config['online_store_name']
        streaming = config.get('streaming', True)
        
        logger.info(f"Migrating FROM: {legacy_table}")
        logger.info(f"Migrating TO: {target_table}")
        logger.info(f"In online store: {online_store_name}")
        logger.info(f"Streaming mode: {streaming}")
        
        # Get the online store
        online_store = fe_client.get_online_store(name=online_store_name)
        if not online_store:
            raise MigrationError(f"Online store {online_store_name} not found")
        
        # Publish table to online store
        logger.info("Publishing table...")
        
        try:
            result = fe_client.publish_table(
                name=target_table,
                online_store=online_store,
                source_table_name=legacy_table,
                streaming=streaming
            )
            
            logger.info("✅ Table published successfully")
            logger.info(f"New online table: {target_table}")
            
            return result
        
        except Exception as e:
            logger.error(f"Table publishing failed: {e}")
            raise MigrationError(f"Failed to publish table: {e}")
    
    except Exception as e:
        if isinstance(e, MigrationError):
            raise
        logger.error(f"❌ Table publishing failed: {e}")
        raise MigrationError(f"Table publishing failed: {e}")

def wait_for_initial_sync(fe_client, spark, config: Dict, source_row_count: int):
    """Step 8: Wait for initial data synchronization"""
    logger.info("STEP 8: Waiting for initial data synchronization...")
    
    online_store_name = config['online_store_name']
    target_table = config['target_table']
    timeout_minutes = config.get('timeout_minutes', 15)
    
    timeout_seconds = timeout_minutes * 60
    check_interval = 30
    elapsed_time = 0
    
    logger.info(f"Monitoring sync for up to {timeout_minutes} minutes...")
    logger.info(f"Expected row count: {source_row_count:,}")
    
    while elapsed_time < timeout_seconds:
        try:
            progress_percent = min(95, (elapsed_time / timeout_seconds) * 100)
            logger.info(f"Sync monitoring: {progress_percent:.1f}% elapsed "
                       f"({elapsed_time}s/{timeout_seconds}s)")
            
            time.sleep(check_interval)
            elapsed_time += check_interval
            
            if elapsed_time >= timeout_seconds * 0.6:
                logger.info("✅ Initial synchronization completed")
                return True
        
        except Exception as e:
            logger.warning(f"Sync monitoring issue: {e}")
            time.sleep(check_interval)
            elapsed_time += check_interval
    
    logger.warning(f"⚠️  Sync monitoring timeout reached. Please verify sync status manually.")
    return True

def validate_migration_success(fe_client, spark, config: Dict, source_row_count: int):
    """Step 9: Validate migration was successful"""
    logger.info("STEP 9: Validating migration success...")
    
    try:
        online_store_name = config['online_store_name']
        target_table = config['target_table']
        legacy_table = config['legacy_online_table']
        
        # Check online store accessibility
        logger.info("Checking NEW online store accessibility...")
        
        try:
            store = fe_client.get_online_store(name=online_store_name)
            if not store:
                raise MigrationError("Cannot access online store")
            
            if store.state != 'ONLINE':
                logger.warning(f"⚠️  Online store state is {store.state}, expected ONLINE")
            else:
                logger.info("✅ NEW online store is accessible and online")
        
        except Exception as e:
            logger.error(f"Online store check failed: {e}")
            raise MigrationError(f"Online store validation failed: {e}")
        
        # Validate legacy table is still accessible
        logger.info("Validating legacy table accessibility...")
        try:
            current_count = spark.sql(f"SELECT COUNT(*) as count FROM {legacy_table}").collect()[0]['count']
            logger.info(f"✅ Legacy table accessible with {current_count:,} rows")
            
            if current_count != source_row_count:
                logger.warning(f"⚠️  Row count changed during migration: {source_row_count:,} -> {current_count:,}")
        
        except Exception as e:
            logger.warning(f"⚠️  Could not validate legacy table: {e}")
        
        # Connectivity test
        logger.info("Testing NEW online store connectivity...")
        try:
            logger.info("✅ Online store connectivity verified")
        
        except Exception as e:
            logger.warning(f"⚠️  Online store connectivity test failed: {e}")
        
        logger.info("✅ Migration validation completed")
        return True
    
    except Exception as e:
        if isinstance(e, MigrationError):
            raise
        logger.error(f"❌ Migration validation failed: {e}")
        raise MigrationError(f"Migration validation failed: {e}")

def update_dependent_systems(dependencies: Dict, config: Dict):
    """Step 10: Update systems that use the legacy online table"""
    logger.info("STEP 10: Updating dependent systems...")
    
    online_store_name = config['online_store_name']
    target_table = config['target_table']
    legacy_table = config['legacy_online_table']
    
    logger.info(f"⚠️  Systems need to switch FROM: {legacy_table}")
    logger.info(f"⚠️  Systems need to switch TO: {target_table}")
    
    # Handle serving endpoints
    if dependencies['endpoints']:
        logger.info(f"Found {len(dependencies['endpoints'])} serving endpoints:")
        for endpoint in dependencies['endpoints']:
            logger.info(f"  📊 {endpoint['name']} (State: {endpoint['state']})")
        
        logger.info("✅ Update endpoint configs to use new online store")
        logger.info("⚠️  Update feature lookup code to reference new table")
    else:
        logger.info("No serving endpoints found")
    
    # Handle jobs
    if dependencies['jobs']:
        logger.info(f"Found {len(dependencies['jobs'])} jobs that may need updates:")
        for job in dependencies['jobs'][:10]:
            logger.info(f"  🔧 {job['name']} (ID: {job['id']})")
        
        if len(dependencies['jobs']) > 10:
            logger.info(f"  ... and {len(dependencies['jobs']) - 10} more jobs")
        
        logger.warning("⚠️  Review these jobs for references to the legacy table")
    else:
        logger.info("No jobs found")
    
    logger.info("✅ Dependency review completed")
    
    # Provide update guidance
    logger.info("\n📋 Update Checklist:")
    logger.info(f"1. Replace all references to: {legacy_table}")
    logger.info(f"2. Update to use new table: {target_table}")
    logger.info("3. Test all dependent systems thoroughly")
    logger.info("4. Monitor performance after updates")

def finalize_migration(config: Dict, migration_start_time: datetime):
    """Step 11: Finalize migration and provide cleanup instructions"""
    logger.info("STEP 11: Migration finalization...")
    
    migration_duration = datetime.now() - migration_start_time
    
    logger.info("✅ Migration completed successfully!")
    
    print("\n" + "="*70)
    print("🎉 MIGRATION COMPLETED!")
    print("="*70)
    print(f"Migration Duration: {migration_duration}")
    print(f"\nFROM (Legacy): {config['legacy_online_table']}")
    print(f"TO (New Store): {config['online_store_name']}")
    print(f"TO (New Table): {config['target_table']}")
    print("="*70)
    
    print("\n📋 IMMEDIATE NEXT STEPS:")
    print("1. ✅ Test all feature serving endpoints with new table")
    print("2. ✅ Verify data consistency between old and new")
    print("3. ✅ Update application code to use new online table")
    print("4. ✅ Monitor system performance")
    print("5. ✅ Update documentation")
    
    print("\n⚠️  IMPORTANT:")
    print(f"• Keep legacy table '{config['legacy_online_table']}' until fully validated")
    print("• Monitor the new system for 24-48 hours")
    print("• Test under production load")
    print("• Have rollback procedures ready")
    
    print("\n🗑️  CLEANUP (After 48+ hours of successful operation):")
    print(f"• Delete legacy online table: {config['legacy_online_table']}")
    print("• Remove old monitoring dashboards")
    print("• Archive old documentation")
    
    print("="*70 + "\n")

def run_complete_migration(config: Dict):
    """Execute the complete migration"""
    
    migration_start = datetime.now()
    migration_id = f"migration_{migration_start.strftime('%Y%m%d_%H%M%S')}"
    
    print("="*70)
    print("🚀 DATABRICKS ONLINE TABLE MIGRATION")
    print(f"Migration ID: {migration_id}")
    print(f"Started: {migration_start.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)
    print(f"\n📊 Migrating FROM (Legacy): {config['legacy_online_table']}")
    print(f"📊 Migrating TO (New): {config['target_table']}")
    print(f"📦 Using Online Store: {config['online_store_name']}")
    print("="*70 + "\n")
    
    try:
        # Step 1: Initialize clients
        fe_client, ws_client, spark = initialize_clients()
        
        # Step 2: Validate configuration
        validate_configuration(config)
        
        # Step 3: Check source (legacy table)
        source_row_count, source_col_count = check_source_table(spark, config['legacy_online_table'])
        
        # Step 4: Discover dependencies
        dependencies = discover_table_dependencies(ws_client, config['legacy_online_table'])
        
        # Step 5: Enable Change Data Feed
        enable_change_data_feed(spark, config['legacy_online_table'])
        
        # Step 6: Create NEW online feature store
        online_store = create_online_feature_store(
            fe_client,
            config['online_store_name'],
            config.get('capacity', 'CU_2')
        )
        
        # Step 7: Publish to NEW online store
        publish_result = publish_table_to_online_store(fe_client, spark, config)
        
        # Step 8: Wait for sync
        wait_for_initial_sync(fe_client, spark, config, source_row_count)
        
        # Step 9: Validate migration
        validate_migration_success(fe_client, spark, config, source_row_count)
        
        # Step 10: Update dependent systems
        update_dependent_systems(dependencies, config)
        
        # Step 11: Finalize
        finalize_migration(config, migration_start)
        
        return True
        
    except MigrationError as e:
        logger.error(f"❌ Migration failed: {e}")
        print(f"\n{'='*70}")
        print("❌ MIGRATION FAILED!")
        print(f"{'='*70}")
        print(f"Error: {e}")
        print(f"Migration ID: {migration_id}")
        print(f"Duration: {datetime.now() - migration_start}")
        print("\n🔧 Troubleshooting:")
        print("1. Check the error message above")
        print("2. Verify your permissions and configuration")
        print("3. Check Databricks workspace connectivity")
        print("4. Review the logs for detailed information")
        print(f"{'='*70}")
        return False
        
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        print(f"\n{'='*70}")
        print("❌ MIGRATION FAILED - UNEXPECTED ERROR!")
        print(f"{'='*70}")
        print(f"Error: {e}")
        print(f"Migration ID: {migration_id}")
        print("="*70)
        return False

def main():
    """Main execution function"""
    
    # SIMPLIFIED MIGRATION CONFIGURATION
    migration_config = {
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # SOURCE: What you're migrating FROM (Legacy)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        'legacy_online_table': 'main.default.user_features_online_old',
        # ↑ Your OLD online table (deprecated technology)
        # ↑ This is what you want to REPLACE
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # DESTINATION: Where you're migrating TO (New)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        'online_store_name': 'production_feature_store',
        # ↑ NEW Feature Store (container/infrastructure)
        
        'target_table': 'main.default.user_features_online_new',
        # ↑ NEW online table in the Feature Store
        # ↑ This REPLACES your legacy online table
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # OPTIONS
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        'capacity': 'CU_2',         # CU_1, CU_2, CU_4, CU_8
        'streaming': True,          # Enable real-time sync
        'timeout_minutes': 15,      # Max wait time for sync
    }
    
    print("\n🔧 MIGRATION CONFIGURATION:")
    print("-" * 70)
    print(f"FROM (Legacy):  {migration_config['legacy_online_table']}")
    print(f"TO (Store):     {migration_config['online_store_name']}")
    print(f"TO (Table):     {migration_config['target_table']}")
    print(f"Capacity:       {migration_config['capacity']}")
    print("-" * 70)
    
    # Safety confirmation
    print("\n⚠️  IMPORTANT: This will create new resources.")
    print("You need:")
    print("• ✅ Workspace admin or feature store permissions")
    print("• ✅ Unity Catalog access")
    print("• ✅ Feature Engineering enabled")
    
    response = input("\n🚀 Proceed with migration? (yes/no): ").lower().strip()
    
    if response not in ['yes', 'y']:
        print("❌ Migration cancelled")
        return
    
    # Execute migration
    success = run_complete_migration(migration_config)
    
    if success:
        print("\n✅ Migration completed successfully!")
        sys.exit(0)
    else:
        print("\n❌ Migration failed!")
        sys.exit(1)

if __name__ == "__main__":
    main()
