import os

# Auto-detect APP_ROOT from this file's location
# services/config.py -> services/ -> <project_root>/
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(APP_ROOT, 'config')
APP_PORT = int(os.environ.get('APP_PORT', '5000'))
ACTIVITY_LOG_PATH = f'{CONFIG_DIR}/activity_log.txt'
MONITORING_CATEGORIES_PATH = f'{CONFIG_DIR}/monitoring_categories.json'
MONITORING_SERVER_MAPPINGS_PATH = f'{CONFIG_DIR}/monitoring_server_mappings.json'
MONITORING_CONFIG_PATH = f'{CONFIG_DIR}/monitoring_config.json'
GLOBAL_CONFIG_PATH = f'{CONFIG_DIR}/global_config.json'
HOST_STAGES_PATH = f'{CONFIG_DIR}/host_stages.json'
USER_PERMISSIONS_PATH = f'{CONFIG_DIR}/user_permissions.json'

LDAP_SERVER = 'localhost:1389'
LDAP_BASE_DN = 'dc=bnet,dc=id'
LDAP_ADMIN_DN = 'cn=admin,dc=bnet,dc=id'
LDAP_ADMIN_PASSWORD = os.environ.get('LDAP_ADMIN_PASSWORD', 'admin')

# Stage definitions
STAGE_NEW = 'new'
STAGE_CS = 'cs'
STAGE_ESCALATED = 'escalated'
STAGE_WATCHLIST = 'watchlist'
STAGE_RESOLVED = 'resolved'

STAGE_LABELS = {
    STAGE_NEW: 'New / Unacknowledged',
    STAGE_CS: 'CR Verification',
    STAGE_ESCALATED: 'Escalated / Pending',
    STAGE_WATCHLIST: 'Watchlist / Flapping',
    STAGE_RESOLVED: 'Resolved',
}

STAGE_RETAIN_MINUTES = 30
