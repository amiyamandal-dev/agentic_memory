# COMMAND ----------

# DBTITLE 1, Initialize Logging System
import logging
from datetime import datetime

class Logger:
    """Custom logger for migration operations"""
    
    LOG_LEVELS = {
        "INFO": "ℹ️ ",
        "SUCCESS": "✅ ",
        "ERROR": "❌ ",
        "WARNING": "⚠️ ",
        "DEBUG": "🔍 "
    }
    
    def __init__(self, name="EndpointMigration"):
        self.name = name
    
    def log(self, level, message, endpoint_name=""):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prefix = self.LOG_LEVELS.get(level, "")
        
        if endpoint_name:
            print(f"{prefix}[{timestamp}] [{endpoint_name}] {message}")
        else:
            print(f"{prefix}[{timestamp}] {message}")
    
    def info(self, message, endpoint=""):
        self.log("INFO", message, endpoint)
    
    def success(self, message, endpoint=""):
        self.log("SUCCESS", message, endpoint)
    
    def error(self, message, endpoint=""):
        self.log("ERROR", message, endpoint)
    
    def warning(self, message, endpoint=""):
        self.log("WARNING", message, endpoint)
    
    def debug(self, message, endpoint=""):
        self.log("DEBUG", message, endpoint)

logger = Logger("EndpointMigration")

# COMMAND ----------

# DBTITLE 1, Set Environment and Get Endpoint List
import json

dbutils.widgets.text(
    "endpoint_names",
    "[]",
    "Endpoint Names (JSON list format: [\"endpoint1\", \"endpoint2\"])"
)

dbutils.widgets.dropdown(
    "env",
    "dev",
    ["dev", "staging", "prod"],
    "Environment Name"
)

endpoint_names_input = dbutils.widgets.get("endpoint_names").strip()
env = dbutils.widgets.get("env")

try:
    endpoint_list = json.loads(endpoint_names_input)
    if not isinstance(endpoint_list, list):
        raise ValueError("Input must be a JSON list")
    if len(endpoint_list) == 0:
        raise ValueError("Endpoint list is empty")
except json.JSONDecodeError as e:
    raise ValueError(f"Invalid JSON format: {str(e)}")

logger.info(f"Processing {len(endpoint_list)} endpoints in environment: {env}")
for ep in endpoint_list:
    logger.debug(f"  - {ep}")

# COMMAND ----------

# DBTITLE 1, Configuration Manager Class
import yaml
import os

class ConfigManager:
    """Manages configuration loading and validation"""
    
    def __init__(self, env):
        self.env = env
        logger.info(f"Initializing ConfigManager for environment: {env}")
    
    def load_config(self):
        """Load configuration from YAML file"""
        try:
            notebook_path = "/Workspace" + os.path.dirname(
                dbutils.notebook.entry_point.getDbutils()
                .notebook()
                .getContext()
                .notebookPath()
                .get()
            )
            
            config_path = os.path.join(notebook_path, f"../config/{self.env}/config-common.yml")
            logger.debug(f"Loading config from: {config_path}")
            
            with open(config_path, "rt") as f:
                config = yaml.safe_load(f)
            
            logger.success(f"Configuration loaded successfully")
            return config
            
        except FileNotFoundError as e:
            logger.error(f"Configuration file not found: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Failed to load configuration: {str(e)}")
            raise
    
    def validate_config(self, config):
        """Validate required configuration keys"""
        required_keys = ['workspace_url']
        
        missing_keys = [key for key in required_keys if not config.get(key)]
        if missing_keys:
            logger.error(f"Missing configuration keys: {', '.join(missing_keys)}")
            raise ValueError(f"Missing required config keys: {missing_keys}")
        
        logger.success("Configuration validation passed")
        return True

# COMMAND ----------

# DBTITLE 1, Utility Functions Class
def safe_parse_json(value, default=None):
    """Safely parse JSON string to object"""
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return default
    return value

def convert_to_dict(obj):
    """Convert PySpark Row or other objects to dictionary"""
    if hasattr(obj, 'asDict'):
        return obj.asDict(recursive=False)
    elif isinstance(obj, dict):
        return obj
    return {}

def row_to_key_value_list(data):
    """Convert data to key-value list format for API"""
    if isinstance(data, str):
        data = safe_parse_json(data, {})
    
    if hasattr(data, "asDict"):
        data = data.asDict()
    
    if not isinstance(data, dict):
        return []
    
    return [{"key": k, "value": v} for k, v in data.items() if v is not None]

# COMMAND ----------

# DBTITLE 1, API Client Class
import requests
import pandas as pd
from databricks.sdk import WorkspaceClient

class APIClient:
    """Manages API communication with Databricks"""
    
    def __init__(self, workspace_host, api_token):
        logger.info("Initializing APIClient")
        self.workspace_host = workspace_host
        self.api_token = api_token
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }
        self.workspace_url = f"{workspace_host}/api/2.0/serving-endpoints"
        
        # Initialize WorkspaceClient with explicit credentials for reliability
        try:
            self.workspace_client = WorkspaceClient(
                host=workspace_host,
                token=api_token
            )
            logger.success("WorkspaceClient initialized with credentials")
        except Exception as e:
            logger.warning(f"WorkspaceClient init with explicit creds failed: {e}, trying default")
            self.workspace_client = WorkspaceClient()
            logger.success("WorkspaceClient initialized with notebook context")
    
    def fetch_all_endpoints(self):
        """Fetch all serving endpoints from API and return as list of dicts"""
        try:
            logger.debug("Fetching all serving endpoints from API")
            
            response = requests.get(
                self.workspace_url,
                headers=self.headers,
                timeout=300
            )
            
            if response.status_code != 200:
                logger.error(f"API returned {response.status_code}: {response.text}")
                return []
            
            endpoints_data = response.json().get("endpoints", [])
            logger.success(f"Fetched {len(endpoints_data)} endpoints from API")
            return endpoints_data
            
        except Exception as e:
            logger.error(f"Failed to fetch endpoints from API: {str(e)}")
            return []
    
    def get_endpoint_details(self, endpoint_name):
        """Get detailed configuration for a specific endpoint"""
        try:
            logger.debug(f"Fetching detailed endpoint configuration", endpoint_name)
            
            url = f"{self.workspace_url}/{endpoint_name}"
            response = requests.get(url, headers=self.headers, timeout=300)
            
            if response.status_code != 200:
                logger.error(f"Failed to get endpoint details: {response.status_code}", endpoint_name)
                return None
            
            endpoint_details = response.json()
            logger.success(f"Endpoint details fetched successfully", endpoint_name)
            return endpoint_details
            
        except Exception as e:
            logger.error(f"Failed to fetch endpoint details: {str(e)}", endpoint_name)
            return None
    
    def make_post_request(self, payload, endpoint_name=""):
        """Make POST request to create endpoint"""
        try:
            logger.debug(f"Making POST request to create endpoint", endpoint_name)
            logger.debug(f"URL: {self.workspace_url}", endpoint_name)
            
            response = requests.post(
                self.workspace_url,
                headers=self.headers,
                json=payload,
                timeout=300
            )
            
            if response.status_code == 200:
                logger.success(f"Endpoint created successfully", endpoint_name)
                return (True, "Endpoint created successfully")
            else:
                error_msg = response.text
                try:
                    error_msg = response.json().get("message", error_msg)
                except:
                    pass
                logger.error(f"API returned {response.status_code}: {error_msg}", endpoint_name)
                return (False, f"HTTP {response.status_code}: {error_msg}")
        
        except requests.exceptions.Timeout:
            logger.error("Request timeout (300s) creating endpoint", endpoint_name)
            return (False, "Request timeout")
        except Exception as e:
            logger.error(f"Request failed: {str(e)}", endpoint_name)
            return (False, str(e))

# COMMAND ----------

# DBTITLE 1, Endpoint Configuration Fetcher Class
class EndpointConfigFetcher:
    """Fetches endpoint configuration from pandas DataFrame"""
    
    def __init__(self, endpoints_df):
        self.endpoints_df = endpoints_df
        logger.info(f"Initializing EndpointConfigFetcher with {len(endpoints_df)} endpoints")
    
    def fetch_endpoint_config(self, endpoint_name):
        """Fetch single endpoint configuration from DataFrame"""
        try:
            logger.debug(f"Fetching configuration from DataFrame", endpoint_name)
            
            # Filter DataFrame for the endpoint
            matching_rows = self.endpoints_df[self.endpoints_df['name'] == endpoint_name]
            
            if len(matching_rows) == 0:
                logger.error(f"Endpoint not found in configuration data", endpoint_name)
                return None
            
            # Convert row to dictionary
            endpoint_config = matching_rows.iloc[0].to_dict()
            
            logger.success(f"Configuration fetched successfully", endpoint_name)
            return endpoint_config
        
        except Exception as e:
            logger.error(f"Failed to fetch configuration: {str(e)}", endpoint_name)
            return None

# COMMAND ----------

# DBTITLE 1, Endpoint Deletion Class
class EndpointDeleter:
    """Handles endpoint deletion"""
    
    def __init__(self, workspace_client):
        self.workspace_client = workspace_client
        logger.info("Initializing EndpointDeleter")
    
    def delete_endpoint(self, endpoint_name, endpoint_config):
        """Delete endpoint if conditions are met"""
        try:
            logger.debug(f"Starting deletion process", endpoint_name)
            
            ai_gateway = endpoint_config.get('ai_gateway')
            if ai_gateway and str(ai_gateway).strip() not in ["", "None", "null"]:
                logger.warning(f"Skipping deletion - AI Gateway already configured", endpoint_name)
                return (False, "Skipped: AI Gateway already configured")
            
            # Verify endpoint exists before deletion
            try:
                logger.debug(f"Verifying endpoint exists", endpoint_name)
                endpoint = self.workspace_client.serving_endpoints.get(endpoint_name)
                if not endpoint:
                    logger.error(f"Endpoint not found in workspace", endpoint_name)
                    return (False, "Endpoint not found in workspace")
            except Exception as e:
                logger.error(f"Endpoint not found: {str(e)}", endpoint_name)
                return (False, f"Endpoint not found")
            
            # Delete endpoint
            logger.debug(f"Sending delete request", endpoint_name)
            self.workspace_client.serving_endpoints.delete(endpoint_name)
            logger.success(f"Endpoint deleted successfully", endpoint_name)
            return (True, f"Endpoint deleted successfully")
        
        except Exception as e:
            logger.error(f"Failed to delete endpoint: {str(e)}", endpoint_name)
            return (False, str(e))

# COMMAND ----------

# DBTITLE 1, Inference Table Renamer Class
class InferenceTableRenamer:
    """Handles inference table renaming"""
    
    def __init__(self):
        logger.info("Initializing InferenceTableRenamer")
    
    def rename_table(self, endpoint_config, endpoint_name):
        """Rename inference table with _legacy suffix"""
        try:
            logger.debug(f"Starting table rename process", endpoint_name)
            
            auto_capture_config = endpoint_config.get('auto_capture_config')
            
            if not auto_capture_config or str(auto_capture_config).strip() in ["", "None", "null"]:
                logger.warning(f"No inference table configuration found", endpoint_name)
                return (None, False, "No inference table configuration found")
            
            # Convert to dictionary if needed
            if hasattr(auto_capture_config, 'asDict'):
                auto_capture_config = auto_capture_config.asDict()
            else:
                auto_capture_config = safe_parse_json(auto_capture_config, {})
            
            if not isinstance(auto_capture_config, dict):
                logger.error(f"Invalid auto_capture_config format", endpoint_name)
                return (None, False, "Invalid auto_capture_config format")
            
            # Extract table details
            catalog_name = auto_capture_config.get('catalog_name')
            schema_name = auto_capture_config.get('schema_name')
            table_name_prefix = auto_capture_config.get('table_name_prefix')
            
            if not all([catalog_name, schema_name, table_name_prefix]):
                logger.error(f"Incomplete inference table configuration", endpoint_name)
                return (None, False, "Incomplete inference table configuration")
            
            old_table_name = f"{catalog_name}.{schema_name}.{table_name_prefix}_payload"
            new_table_name = f"{old_table_name}_legacy"
            
            # Check if table exists using modern Spark catalog API
            logger.debug(f"Checking if table exists: {old_table_name}", endpoint_name)
            try:
                table_exists = spark.catalog.tableExists(old_table_name)
                if not table_exists:
                    logger.error(f"Table does not exist: {old_table_name}", endpoint_name)
                    return (old_table_name, False, f"Table does not exist")
            except Exception as e:
                logger.error(f"Failed to check table existence: {str(e)}", endpoint_name)
                return (old_table_name, False, f"Failed to check table existence")
            
            # Rename table using proper SQL syntax with backticks
            logger.debug(f"Executing rename from {old_table_name} to {new_table_name}", endpoint_name)
            spark.sql(f"ALTER TABLE `{old_table_name}` RENAME TO `{new_table_name}`")
            logger.success(f"Table renamed to {new_table_name}", endpoint_name)
            return (old_table_name, True, f"Table renamed successfully")
        
        except Exception as e:
            logger.error(f"Failed to rename table: {str(e)}", endpoint_name)
            return (None, False, str(e))

# COMMAND ----------

# DBTITLE 1, Endpoint Creator Class
class EndpointCreator:
    """Creates new endpoint with AI Gateway configuration"""
    
    def __init__(self, api_client):
        self.api_client = api_client
        logger.info("Initializing EndpointCreator")
    
    def create_endpoint_with_gateway(self, endpoint_config, endpoint_name):
        """Create new endpoint with AI Gateway"""
        try:
            logger.debug(f"Starting endpoint creation process", endpoint_name)
            
            # Validate endpoint name
            endpoint_name_create = endpoint_config.get('name')
            if not endpoint_name_create:
                logger.error(f"Endpoint name not found in config", endpoint_name)
                return (None, False, "Endpoint name not found")
            
            # Parse served_entities
            logger.debug(f"Parsing served_entities", endpoint_name)
            served_entities = endpoint_config.get('served_entities', [])
            served_entities = safe_parse_json(served_entities, [])
            
            if not isinstance(served_entities, list) or len(served_entities) == 0:
                logger.error(f"No served entities found", endpoint_name)
                return (endpoint_name_create, False, "No served entities found")
            
            served_entity = served_entities[0]
            if hasattr(served_entity, 'asDict'):
                served_entity = served_entity.asDict()
            
            # Parse auto_capture_config
            logger.debug(f"Parsing auto_capture_config", endpoint_name)
            auto_capture_config = endpoint_config.get('auto_capture_config')
            if hasattr(auto_capture_config, 'asDict'):
                auto_capture_config = auto_capture_config.asDict()
            else:
                auto_capture_config = safe_parse_json(auto_capture_config, {})
            
            if not auto_capture_config or not isinstance(auto_capture_config, dict):
                logger.error(f"Missing or invalid auto_capture_config", endpoint_name)
                return (endpoint_name_create, False, "Missing auto_capture_config")
            
            # Parse tags
            tags = endpoint_config.get('tags', [])
            tags = safe_parse_json(tags, [])
            if not isinstance(tags, list):
                tags = []
            
            # Build payload for API
            logger.debug(f"Building API payload", endpoint_name)
            payload = {
                "name": endpoint_name_create,
                "config": {
                    "served_entities": [
                        {
                            "entity_name": served_entity.get('entity_name'),
                            "entity_version": served_entity.get('entity_version'),
                            "environment_vars": row_to_key_value_list(served_entity.get('environment_vars', {})),
                            "min_provisioned_throughput": served_entity.get('min_provisioned_throughput'),
                            "max_provisioned_throughput": served_entity.get('max_provisioned_throughput'),
                            "scale_to_zero_enabled": served_entity.get('scale_to_zero_enabled'),
                            "workload_size": served_entity.get('workload_size'),
                            "workload_type": served_entity.get('workload_type'),
                        }
                    ]
                },
                "ai_gateway": {
                    "inference_table_config": {
                        "catalog_name": auto_capture_config.get('catalog_name'),
                        "schema_name": auto_capture_config.get('schema_name'),
                        "table_name_prefix": auto_capture_config.get('table_name_prefix'),
                        "enabled": auto_capture_config.get('enabled', True),
                    }
                },
            }
            
            # Add optional fields
            description = endpoint_config.get('description')
            if description and str(description).strip():
                payload["description"] = description
            
            route_optimized = endpoint_config.get('route_optimized')
            if route_optimized is not None:
                payload["route_optimized"] = route_optimized
            
            if tags:
                payload["tags"] = tags
            
            logger.debug(f"Payload prepared:\n{json.dumps(payload, indent=2, default=str)}", endpoint_name)
            
            # Make API call
            success, message = self.api_client.make_post_request(payload, endpoint_name)
            return (endpoint_name_create, success, message)
        
        except Exception as e:
            logger.error(f"Exception during creation: {str(e)}", endpoint_name)
            return (endpoint_config.get('name', 'unknown'), False, str(e))

# COMMAND ----------

# DBTITLE 1, Migration Orchestrator Class
class MigrationOrchestrator:
    """Orchestrates the entire migration process"""
    
    def __init__(self, api_client, fetcher, deleter, renamer, creator):
        self.api_client = api_client
        self.fetcher = fetcher
        self.deleter = deleter
        self.renamer = renamer
        self.creator = creator
        self.results = []
        logger.info("Initializing MigrationOrchestrator")
    
    def process_endpoint(self, endpoint_name):
        """Process single endpoint through all migration steps"""
        logger.info(f"\n{'='*80}")
        logger.info(f"Starting migration for endpoint: {endpoint_name}")
        logger.info(f"{'='*80}")
        
        migration_result = {
            "endpoint_name": endpoint_name,
            "delete": None,
            "rename": None,
            "create": None,
            "overall_status": "FAILED"
        }
        
        # Step 1: Fetch configuration
        logger.info(f"Step 1/4: Fetching configuration")
        endpoint_config = self.fetcher.fetch_endpoint_config(endpoint_name)
        if not endpoint_config:
            logger.error(f"Migration failed - could not fetch configuration", endpoint_name)
            self.results.append(migration_result)
            return
        
        # Step 2: Delete endpoint
        logger.info(f"Step 2/4: Deleting endpoint")
        delete_success, delete_msg = self.deleter.delete_endpoint(endpoint_name, endpoint_config)
        migration_result["delete"] = {
            "success": delete_success,
            "message": delete_msg
        }
        
        if not delete_success:
            logger.warning(f"Skipping remaining steps due to delete failure", endpoint_name)
            self.results.append(migration_result)
            return
        
        # Step 3: Rename inference table
        logger.info(f"Step 3/4: Renaming inference table")
        table_name, rename_success, rename_msg = self.renamer.rename_table(endpoint_config, endpoint_name)
        migration_result["rename"] = {
            "table_name": table_name,
            "success": rename_success,
            "message": rename_msg
        }
        
        if not rename_success:
            logger.warning(f"Proceeding with creation despite rename failure", endpoint_name)
        
        # Step 4: Create endpoint with gateway
        logger.info(f"Step 4/4: Creating endpoint with AI Gateway configuration")
        ep_name, create_success, create_msg = self.creator.create_endpoint_with_gateway(endpoint_config, endpoint_name)
        migration_result["create"] = {
            "success": create_success,
            "message": create_msg
        }
        
        # Determine overall status
        if delete_success and create_success:
            migration_result["overall_status"] = "SUCCESS"
            logger.success(f"Migration completed successfully", endpoint_name)
        else:
            logger.warning(f"Migration completed with issues", endpoint_name)
        
        self.results.append(migration_result)
    
    def process_all_endpoints(self, endpoint_list):
        """Process all endpoints in the list sequentially"""
        logger.info(f"\n{'='*80}")
        logger.info(f"Starting batch migration for {len(endpoint_list)} endpoint(s)")
        logger.info(f"{'='*80}\n")
        
        for idx, endpoint_name in enumerate(endpoint_list, 1):
            logger.info(f"Processing endpoint {idx}/{len(endpoint_list)}: {endpoint_name}")
            try:
                self.process_endpoint(endpoint_name)
            except Exception as e:
                logger.error(f"Unexpected error processing endpoint: {str(e)}", endpoint_name)
                self.results.append({
                    "endpoint_name": endpoint_name,
                    "delete": None,
                    "rename": None,
                    "create": None,
                    "overall_status": "FAILED"
                })
        
        logger.info(f"\n{'='*80}")
        logger.info(f"Batch migration completed")
        logger.info(f"{'='*80}\n")
    
    def get_results(self):
        """Get migration results"""
        return self.results

# COMMAND ----------

# DBTITLE 1, Initialize and Run Migration
logger.info("Initializing migration system...")

# Load configuration
config_manager = ConfigManager(env)
config = config_manager.load_config()
config_manager.validate_config(config)

# Extract configuration values
DATABRICKS_HOST = config.get('workspace_url')

logger.success(f"Configuration loaded - Host: {DATABRICKS_HOST}")

# Get API token - using modern Databricks context API
try:
    context = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
    DATABRICKS_TOKEN = context.apiToken().get()
    logger.success("API token retrieved successfully")
except Exception as e:
    logger.error(f"Failed to retrieve API token: {str(e)}")
    raise

# Initialize API Client
api_client = APIClient(DATABRICKS_HOST, DATABRICKS_TOKEN)

# Step 1: Fetch all endpoints from API
logger.info("\nFetching all endpoint configurations from Databricks API...")
endpoints_list = api_client.fetch_all_endpoints()

if not endpoints_list:
    logger.error("No endpoints found or failed to fetch from API")
    raise Exception("Failed to fetch endpoints from API")

logger.success(f"Successfully fetched {len(endpoints_list)} endpoints")

# Step 2: Convert to pandas DataFrame
logger.info("Converting endpoints data to pandas DataFrame...")
endpoints_df = pd.DataFrame(endpoints_list)
logger.success(f"Created DataFrame with shape: {endpoints_df.shape}")

# Display DataFrame columns for verification
logger.info(f"DataFrame columns: {', '.join(endpoints_df.columns.tolist())}")

# Initialize components with DataFrame
fetcher = EndpointConfigFetcher(endpoints_df)
deleter = EndpointDeleter(api_client.workspace_client)
renamer = InferenceTableRenamer()
creator = EndpointCreator(api_client)

# Initialize orchestrator
orchestrator = MigrationOrchestrator(api_client, fetcher, deleter, renamer, creator)

# Process all endpoints sequentially
orchestrator.process_all_endpoints(endpoint_list)

# COMMAND ----------

# DBTITLE 1, Generate Results Summary
from pyspark.sql.types import StructType, StructField, StringType, BooleanType
from pyspark.sql.functions import lit, current_timestamp, from_utc_timestamp, date_format

results = orchestrator.get_results()

# Flatten results for DataFrame
flattened_results = []
for result in results:
    flattened_results.append((
        result["endpoint_name"],
        result["delete"]["success"] if result["delete"] else False,
        result["delete"]["message"] if result["delete"] else "Not processed",
        result["rename"]["success"] if result["rename"] else False,
        result["rename"]["message"] if result["rename"] else "Not processed",
        result["create"]["success"] if result["create"] else False,
        result["create"]["message"] if result["create"] else "Not processed",
        result["overall_status"]
    ))

schema = StructType([
    StructField("endpoint_name", StringType(), True),
    StructField("delete_success", BooleanType(), True),
    StructField("delete_message", StringType(), True),
    StructField("rename_success", BooleanType(), True),
    StructField("rename_message", StringType(), True),
    StructField("create_success", BooleanType(), True),
    StructField("create_message", StringType(), True),
    StructField("overall_status", StringType(), True),
])

results_df = spark.createDataFrame(flattened_results, schema=schema)

results_df = results_df.withColumn(
    "date",
    date_format(
        from_utc_timestamp(current_timestamp(), "Australia/Sydney"),
        "dd-MM-yyyy HH:mm"
    )
).withColumn("env", lit(env))

logger.info(f"\nMigration Results Summary:")
display(results_df)

# COMMAND ----------

# DBTITLE 1, Final Summary Report
logger.info(f"\n{'='*80}")
logger.info("FINAL MIGRATION REPORT")
logger.info(f"{'='*80}")

total_endpoints = len(results)
successful_migrations = sum(1 for r in results if r["overall_status"] == "SUCCESS")
failed_migrations = total_endpoints - successful_migrations

logger.info(f"Total Endpoints Processed: {total_endpoints}")
logger.success(f"Successful Migrations: {successful_migrations}")
logger.error(f"Failed Migrations: {failed_migrations}")

logger.info(f"\nDetails:")
for result in results:
    status_icon = "✅" if result["overall_status"] == "SUCCESS" else "❌"
    logger.info(f"{status_icon} {result['endpoint_name']}: {result['overall_status']}")

logger.info(f"\n{'='*80}")
