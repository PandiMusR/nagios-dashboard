from __future__ import annotations

from flask import Blueprint, render_template, request, redirect, session, jsonify, flash, send_file, Response
import os, json, re

from services.config import APP_ROOT, MONITORING_CATEGORIES_PATH, MONITORING_SERVER_MAPPINGS_PATH, MONITORING_CONFIG_PATH
from services.ldap_service import log_activity
from services.shared_helpers import get_nagios_servers, get_monitoring_categories
from utils.permissions import check_permission

monitoring_settings_bp = Blueprint('monitoring_settings', __name__)


@monitoring_settings_bp.route('/monitoring-settings')
def monitoring_settings() -> str | Response:
    """GET /monitoring-settings — render the monitoring settings page."""
    if 'username' not in session:
        return redirect('/')
    
    if not check_permission('monitoring_settings'):
        flash('Access denied. You do not have permission to access this page.', 'error')
        return redirect('/dashboard')
    
    categories = get_monitoring_categories()
    
    # Load server mappings
    server_mappings = {}
    try:
        if os.path.exists(MONITORING_SERVER_MAPPINGS_PATH):
            with open(MONITORING_SERVER_MAPPINGS_PATH, 'r') as f:
                server_mappings = json.load(f)
    except (json.JSONDecodeError, OSError):
        pass
    
    # Load monitoring settings
    monitoring_config = {'refresh_interval': 30, 'alarm_settings': {}}
    try:
        if os.path.exists(MONITORING_CONFIG_PATH):
            with open(MONITORING_CONFIG_PATH, 'r') as f:
                monitoring_config = json.load(f)
    except (json.JSONDecodeError, OSError):
        pass
    
    # Get all nagios servers
    nagios_servers_list = get_nagios_servers()
    
    return render_template('monitoring_settings.html', username=session['username'], 
                         categories=categories, server_mappings=server_mappings,
                         nagios_servers_list=nagios_servers_list,
                         monitoring_config=monitoring_config,
                         nagios_servers=get_nagios_servers(), monitoring_categories=get_monitoring_categories())


@monitoring_settings_bp.route('/monitoring-settings/edit-category', methods=['POST'])
def edit_monitoring_category() -> str | Response:
    """POST /monitoring-settings/edit-category — update a category's settings."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('monitoring_settings'):
        return jsonify({'error': 'Access denied'}), 403
    
    category = request.form.get('category')
    use_service_plugin = request.form.get('use_service_plugin', 'false') == 'true'
    
    try:
        config = {}
        if os.path.exists(MONITORING_CONFIG_PATH):
            with open(MONITORING_CONFIG_PATH, 'r') as f:
                config = json.load(f)
        
        if 'category_settings' not in config:
            config['category_settings'] = {}
        
        config['category_settings'][category] = {
            'use_service_plugin': use_service_plugin
        }
        
        with open(MONITORING_CONFIG_PATH, 'w') as f:
            json.dump(config, f)
        
        flash(f'Category "{category}" settings updated!', 'success')
    except Exception as e:
        flash(f'Failed to update category: {str(e)}', 'error')
    
    return redirect('/monitoring-settings')


@monitoring_settings_bp.route('/monitoring-settings/add', methods=['POST'])
def add_monitoring_category() -> str | Response:
    """POST /monitoring-settings/add — add a new monitoring category."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('monitoring_settings'):
        flash('Access denied. You do not have permission to modify monitoring settings.', 'error')
        return redirect('/dashboard')
    
    raw_category = (request.form.get('category') or '').strip()
    if not raw_category:
        flash('Category name is required!', 'error')
        return redirect('/monitoring-settings')

    category = re.sub(r'[^a-z0-9-]+', '-', raw_category.lower().replace(' ', '-')).strip('-')
    if not category:
        flash('Category name must contain letters or numbers!', 'error')
        return redirect('/monitoring-settings')

    use_service_plugin = request.form.get('use_service_plugin', 'false') == 'true'
    
    try:
        categories = get_monitoring_categories()
        
        if category not in categories:
            categories.append(category)
            with open(MONITORING_CATEGORIES_PATH, 'w') as f:
                json.dump(categories, f)
            
            # Save service plugin setting
            config = {}
            if os.path.exists(MONITORING_CONFIG_PATH):
                with open(MONITORING_CONFIG_PATH, 'r') as f:
                    config = json.load(f)
            
            if 'category_settings' not in config:
                config['category_settings'] = {}
            
            config['category_settings'][category] = {
                'use_service_plugin': use_service_plugin
            }
            
            with open(MONITORING_CONFIG_PATH, 'w') as f:
                json.dump(config, f)
            
            flash(f'Category "{category}" added successfully!', 'success')
        else:
            flash(f'Category "{category}" already exists!', 'error')
    except Exception as e:
        flash(f'Failed to add category: {str(e)}', 'error')
    
    return redirect('/monitoring-settings')


@monitoring_settings_bp.route('/monitoring-settings/delete/<category>', methods=['POST'])
def delete_monitoring_category(category: str) -> str | Response:
    """POST /monitoring-settings/delete/<category> — delete a monitoring category."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('monitoring_settings'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        categories = get_monitoring_categories()
        
        if category in categories:
            categories.remove(category)
            with open(MONITORING_CATEGORIES_PATH, 'w') as f:
                json.dump(categories, f)
            flash(f'Category "{category}" deleted successfully!', 'success')
        else:
            flash(f'Category "{category}" not found!', 'error')
    except Exception as e:
        flash(f'Failed to delete category: {str(e)}', 'error')
    
    return redirect('/monitoring-settings')


@monitoring_settings_bp.route('/monitoring-settings/map-server', methods=['POST'])
def map_server_to_category() -> str | Response:
    """POST /monitoring-settings/map-server — map a server to a category."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('monitoring_settings'):
        return jsonify({'error': 'Access denied'}), 403
    
    server = request.form.get('server')
    category = request.form.get('category')
    
    try:
        mappings = {}
        if os.path.exists(MONITORING_SERVER_MAPPINGS_PATH):
            with open(MONITORING_SERVER_MAPPINGS_PATH, 'r') as f:
                mappings = json.load(f)
        
        # Hapus server dari semua kategori lain terlebih dahulu
        for cat in mappings:
            if server in mappings[cat]:
                mappings[cat].remove(server)
        
        if category not in mappings:
            mappings[category] = []
        
        if server not in mappings[category]:
            mappings[category].append(server)
            with open(MONITORING_SERVER_MAPPINGS_PATH, 'w') as f:
                json.dump(mappings, f)
            flash(f'Server "{server}" mapped to "{category}"!', 'success')
        else:
            flash(f'Server "{server}" already in "{category}"!', 'error')
    except Exception as e:
        flash(f'Failed to map server: {str(e)}', 'error')
    
    return redirect('/monitoring-settings')


@monitoring_settings_bp.route('/monitoring-settings/update-config', methods=['POST'])
def update_monitoring_config() -> str | Response:
    """POST /monitoring-settings/update-config — update monitoring configuration."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('monitoring_settings'):
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        config = {}
        if os.path.exists(MONITORING_CONFIG_PATH):
            with open(MONITORING_CONFIG_PATH, 'r') as f:
                config = json.load(f)
        
        # Always preserve existing refresh_interval if not explicitly updating
        refresh_interval = request.form.get('refresh_interval', type=int)
        if refresh_interval:
            config['refresh_interval'] = refresh_interval
        elif 'refresh_interval' not in config:
            config['refresh_interval'] = 30
        
        category = request.form.get('category')
        
        if category:
            alarm_down = request.form.get('alarm_down') == 'on'
            alarm_up = request.form.get('alarm_up') == 'on'
            
            if 'alarm_settings' not in config:
                config['alarm_settings'] = {}
            
            # Preserve existing sound paths
            existing_settings = config.get('alarm_settings', {}).get(category, {})
            sound_down_path = existing_settings.get('sound_down')
            sound_up_path = existing_settings.get('sound_up')
            
            # Handle sound file uploads
            sound_down_file = request.files.get('sound_down')
            sound_up_file = request.files.get('sound_up')
            
            # Create sound directory if not exists
            sound_dir = f'{APP_ROOT}/static/assets/sound'
            os.makedirs(sound_dir, exist_ok=True)
            
            ALLOWED_SOUND_EXTENSIONS = {'.wav', '.mp3', '.ogg', '.m4a', '.aac'}

            if sound_down_file and sound_down_file.filename:
                ext = os.path.splitext(sound_down_file.filename)[1].lower()
                if ext not in ALLOWED_SOUND_EXTENSIONS:
                    flash(f'Invalid file type: {ext}. Allowed: {", ".join(sorted(ALLOWED_SOUND_EXTENSIONS))}', 'danger')
                    return redirect(url_for('monitoring_settings.monitoring_settings'))
                filename = f'alarm_down_{category}{ext}'
                sound_down_path = os.path.join(sound_dir, filename)
                sound_down_file.save(sound_down_path)
            
            if sound_up_file and sound_up_file.filename:
                ext = os.path.splitext(sound_up_file.filename)[1].lower()
                if ext not in ALLOWED_SOUND_EXTENSIONS:
                    flash(f'Invalid file type: {ext}. Allowed: {", ".join(sorted(ALLOWED_SOUND_EXTENSIONS))}', 'danger')
                    return redirect(url_for('monitoring_settings.monitoring_settings'))
                filename = f'alarm_up_{category}{ext}'
                sound_up_path = os.path.join(sound_dir, filename)
                sound_up_file.save(sound_up_path)
            
            config['alarm_settings'][category] = {
                'alarm_down': alarm_down,
                'alarm_up': alarm_up,
                'sound_down': sound_down_path,
                'sound_up': sound_up_path
            }
        
        with open(MONITORING_CONFIG_PATH, 'w') as f:
            json.dump(config, f)
        
        flash('Monitoring settings updated!', 'success')
    except Exception as e:
        flash(f'Failed to update settings: {str(e)}', 'error')
    
    return redirect('/monitoring-settings')


@monitoring_settings_bp.route('/monitoring-settings/update-cr-reset', methods=['POST'])
def update_cr_reset_config() -> Response:
    """POST /monitoring-settings/update-cr-reset — save per-category CR Auto-Reset config."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('monitoring_settings'):
        flash('Access denied.', 'error')
        return redirect('/dashboard')

    category = request.form.get('category', '').strip()
    cr_reset_hours = request.form.get('cr_reset_hours', '').strip()
    cr_reset_interval_days = request.form.get('cr_reset_interval_days', '0').strip()
    cr_reset_grace_hours = request.form.get('cr_reset_grace_hours', '0').strip()

    if not category:
        flash('Category is required.', 'error')
        return redirect('/monitoring-settings')

    try:
        config = {}
        if os.path.exists(MONITORING_CONFIG_PATH):
            with open(MONITORING_CONFIG_PATH, 'r') as f:
                config = json.load(f)

        if 'category_settings' not in config:
            config['category_settings'] = {}
        if category not in config['category_settings']:
            config['category_settings'][category] = {}

        config['category_settings'][category]['cr_reset_hours'] = cr_reset_hours
        config['category_settings'][category]['cr_reset_interval_days'] = int(cr_reset_interval_days) if cr_reset_interval_days.isdigit() else 0
        config['category_settings'][category]['cr_reset_grace_hours'] = int(cr_reset_grace_hours) if cr_reset_grace_hours.isdigit() else 0

        with open(MONITORING_CONFIG_PATH, 'w') as f:
            json.dump(config, f)

        log_activity('Update CR Auto-Reset', f'Category "{category}": hours={cr_reset_hours}, interval={cr_reset_interval_days} days, grace={cr_reset_grace_hours}h')
        flash(f'CR Auto-Reset for "{category}" saved! Changes take effect within 30 seconds.', 'success')
    except Exception as e:
        log_activity('Update CR Auto-Reset Failed', str(e))
        flash(f'Failed to save: {str(e)}', 'error')

    return redirect('/monitoring-settings')


@monitoring_settings_bp.route('/monitoring/<page>/config')
def monitoring_config(page: str) -> Response | tuple[Response, int]:
    """GET /monitoring/<page>/config — return monitoring config for a page."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('monitoring_settings'):
        return jsonify({'error': 'Access denied'}), 403
    
    config = {'refresh_interval': 30, 'alarm_settings': {}}
    try:
        if os.path.exists(MONITORING_CONFIG_PATH):
            with open(MONITORING_CONFIG_PATH, 'r') as f:
                config = json.load(f)
    except (json.JSONDecodeError, OSError):
        pass
    
    return jsonify({
        'refresh_interval': config.get('refresh_interval', 30),
        'alarm_down': config.get('alarm_settings', {}).get(page, {}).get('alarm_down', False),
        'alarm_up': config.get('alarm_settings', {}).get(page, {}).get('alarm_up', False),
        'sound_down': config.get('alarm_settings', {}).get(page, {}).get('sound_down'),
        'sound_up': config.get('alarm_settings', {}).get(page, {}).get('sound_up')
    })


@monitoring_settings_bp.route('/alarm-sound/<path:filename>')
def alarm_sound(filename: str) -> Response | tuple[Response, int]:
    """GET /alarm-sound/<filename> — serve an alarm sound file."""
    sound_path = f'{APP_ROOT}/static/assets/sound/{filename}'
    if os.path.exists(sound_path):
        # Determine mimetype based on file extension
        ext = filename.split('.')[-1].lower()
        mimetype = 'audio/wav' if ext == 'wav' else 'audio/mpeg'
        return send_file(sound_path, mimetype=mimetype)
    return jsonify({'error': 'File not found'}), 404


@monitoring_settings_bp.route('/monitoring-settings/unmap-server', methods=['POST'])
def unmap_server_from_category() -> str | Response:
    """POST /monitoring-settings/unmap-server — remove a server from a category."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not check_permission('monitoring_settings'):
        return jsonify({'error': 'Access denied'}), 403
    
    server = request.form.get('server')
    category = request.form.get('category')
    
    try:
        mappings = {}
        if os.path.exists(MONITORING_SERVER_MAPPINGS_PATH):
            with open(MONITORING_SERVER_MAPPINGS_PATH, 'r') as f:
                mappings = json.load(f)
        
        if category in mappings and server in mappings[category]:
            mappings[category].remove(server)
            with open(MONITORING_SERVER_MAPPINGS_PATH, 'w') as f:
                json.dump(mappings, f)
            flash(f'Server "{server}" removed from "{category}"!', 'success')
        else:
            flash(f'Mapping not found!', 'error')
    except Exception as e:
        flash(f'Failed to unmap server: {str(e)}', 'error')
    
    return redirect('/monitoring-settings')
