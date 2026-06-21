from flask import Flask, request, session
import os
import subprocess
import json

from services.encryption import load_or_create_secret_key, init_encryption
from services.ldap_service import check_ldap_server, setup_ldap_structure, CONFIG_DIR
from services.config import APP_PORT
from services.active_users import active_users
from services.scheduler import start_cr_reset_scheduler

app = Flask(__name__)

# Persistent secret key — survives restarts, used for session encryption + Fernet
app.secret_key = load_or_create_secret_key()

# Initialize Fernet encryption (derived from secret key)
init_encryption(app.secret_key)

# Ensure config directory exists
os.makedirs(CONFIG_DIR, exist_ok=True)


@app.before_request
def track_active_user():
    """Update active user tracker on every authenticated request."""
    if 'username' in session:
        active_users.update(
            username=session['username'],
            ip=request.remote_addr or 'unknown',
            role=session.get('role', 'user')
        )


# Auto-setup LDAP structure on first run
ldap_status = check_ldap_server()
if ldap_status in ['created', 'started']:
    setup_ldap_structure()
    print("LDAP server is ready. Please create first admin user.")

# Per-category CR Verification auto-reset scheduler
start_cr_reset_scheduler()

# Register blueprints
from blueprints.auth import auth_bp
from blueprints.dashboard import dashboard_bp
from blueprints.servers import servers_bp
from blueprints.users import users_bp
from blueprints.monitoring import monitoring_bp
from blueprints.host_manager import host_manager_bp
from blueprints.monitoring_settings import monitoring_settings_bp
from blueprints.global_settings import global_settings_bp
from blueprints.nagios_proxy import nagios_proxy_bp
from blueprints.monitoring_intens import monitoring_intens_bp
from blueprints.api import api_bp

app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(servers_bp)
app.register_blueprint(users_bp)
app.register_blueprint(monitoring_bp)
app.register_blueprint(host_manager_bp)
app.register_blueprint(monitoring_settings_bp)
app.register_blueprint(global_settings_bp)
app.register_blueprint(nagios_proxy_bp)
app.register_blueprint(monitoring_intens_bp)
app.register_blueprint(api_bp)

if __name__ == '__main__':
    from waitress import serve
    print(f" * Starting Waitress WSGI server on 0.0.0.0:{APP_PORT} (threads=8)")
    serve(app, host='0.0.0.0', port=APP_PORT, threads=8)
