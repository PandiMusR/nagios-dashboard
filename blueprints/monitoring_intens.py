from __future__ import annotations

from flask import Blueprint, render_template, redirect, session, jsonify, flash, Response
import time, traceback

from services.uptime_kuma import get_uptime_kuma_config, remove_host_from_uptime_kuma
from services.ldap_service import log_activity
from utils.permissions import check_permission

monitoring_intens_bp = Blueprint('monitoring_intens', __name__)


@monitoring_intens_bp.route('/monitoring-intens')
def monitoring_intens() -> str | Response:
    """GET /monitoring-intens — render the Uptime Kuma monitoring page."""
    if 'username' not in session:
        return redirect('/login')
    
    if not check_permission('monitoring'):
        flash('Access denied', 'error')
        return redirect('/dashboard')
    
    return render_template('monitoring_intens.html')


@monitoring_intens_bp.route('/api/monitoring-intens/monitors')
def get_uptime_kuma_monitors() -> tuple[dict, int]:
    """API endpoint — fetch all Uptime Kuma monitors via Socket.IO."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    if not check_permission('monitoring'):
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    try:
        try:
            import socketio
        except ImportError:
            return jsonify({'success': False, 'error': 'Socket.IO library not available'})
        
        config = get_uptime_kuma_config()
        if not config:
            return jsonify({'success': False, 'error': 'Uptime Kuma not configured'})
        
        # Create Socket.IO client
        sio = socketio.Client(ssl_verify=False, reconnection=False)
        
        # Storage for received data
        received_data = {
            'monitor_list': {},
            'ready': False
        }
        
        def on_monitorList(data):
            """Receive full monitor list after login"""
            received_data['monitor_list'] = data or {}
            received_data['ready'] = True
        
        # Register event handlers
        sio.on('monitorList', on_monitorList)
        
        # Connect to Uptime Kuma
        try:
            sio.connect(config['url'], transports=['websocket', 'polling'], wait_timeout=3)
        except Exception as e:
            return jsonify({'success': False, 'error': f'Connection failed: {str(e)}'})
        
        import time
        time.sleep(1)
        
        # Login with API key
        login_response = {}
        
        def on_login_callback(res):
            login_response.update(res or {})
        
        sio.emit('login', {
            'username': config.get('uptime_kuma_username', 'admin'),
            'password': config['api_key']
        }, callback=on_login_callback)
        
        # Wait for login and monitor list
        timeout = time.time() + 5
        while time.time() < timeout:
            if received_data['ready'] and login_response:
                break
            time.sleep(0.1)
        
        sio.disconnect()
        
        # Check login status
        if not login_response.get('ok'):
            return jsonify({
                'success': False,
                'error': f"Login failed: {login_response.get('msg', 'Invalid API key')}"
            })
        
        # Format and return monitor data
        monitors = []
        for monitor_id, monitor in received_data['monitor_list'].items():
            if isinstance(monitor, dict):
                monitors.append({
                    'id': monitor.get('id', monitor_id),
                    'name': monitor.get('name', 'Unknown'),
                    'type': monitor.get('type', 'unknown'),
                    'url': monitor.get('url'),
                    'hostname': monitor.get('hostname'),
                    'status': monitor.get('status', 2),
                    'active': monitor.get('active', True),
                    'lastHeartbeat': monitor.get('lastHeartbeat'),
                    'avgPing': monitor.get('avgPing'),
                    'uptime': monitor.get('uptime', 0)
                })
        
        return jsonify({'success': True, 'monitors': monitors})
        
    except Exception as e:
        print(f"Error in get_uptime_kuma_monitors: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Server error: {str(e)}'})


@monitoring_intens_bp.route('/api/monitoring-intens/monitors/<int:monitor_id>', methods=['DELETE'])
def delete_uptime_kuma_monitor(monitor_id: int) -> tuple[dict, int]:
    """API endpoint — delete a Uptime Kuma monitor by ID."""
    if 'username' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    if not check_permission('monitoring'):
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    try:
        success, msg = remove_host_from_uptime_kuma(monitor_id)
        
        if success:
            log_activity('Remove Host from Uptime Kuma', f'Monitor ID: {monitor_id}')
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': msg})
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
