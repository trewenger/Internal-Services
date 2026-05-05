import logging
import os
import threading
from datetime import datetime

from flask import Blueprint, abort, jsonify, render_template, request, send_from_directory

from API_Service_Network.DigitalDisplayBoard.ddb_data import SignageConfig, SignageLog, Media
from blueprints.auth import access_required, login_required
from config import Config

signage_bp = Blueprint('signage', __name__)
logger = logging.getLogger(__name__)
app_configs = Config()
signage_config = SignageConfig()
signage_log = SignageLog()
media = Media()

# ============================================================================
# Routes
# ============================================================================

# load index page
@signage_bp.route('/')
@access_required('signage')
def index():
    data = signage_config.get_all()
    slideshows = data.get("slideshows")
    media = data.get("media")
    return render_template('signage/index.html', slideshows=slideshows, media=media)

# ---------------------- api routes --------------------------------
# get all data
@signage_bp.route('/api/get-data')
@access_required('signage')
def get_slideshows():
    data = signage_config.get_all()
    return jsonify({'success': True, 'slideshows': data.get('slideshows'), 'media': data.get('media')})

# create a new slideshow
@signage_bp.route('/api/slideshow/create', methods=['POST'])
@access_required('signage')
def api_create_slideshow():
    body = request.get_json(force=True) or {}
    name = (body.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'error': 'Name is required'}), 400
    description = (body.get('description') or '').strip()
    speed_secs  = max(1, int(body.get('speed_secs', 20) or 20))
    key, cfg    = signage_config.create(name, description, speed_secs)
    return jsonify({'success': True, 'key': key, 'config': cfg})

# delete a slideshow
@signage_bp.route('/api/slideshow/<name>/delete', methods=['POST'])
@access_required('signage')
def api_delete_slideshow(name):
    if not signage_config.delete(name):
        return jsonify({'success': False, 'error': 'Slideshow not found'}), 404
    return jsonify({'success': True})

# update slideshow settings
@signage_bp.route('/api/update/<name>', methods=['POST'])
@access_required('signage')
def api_update_slideshow(name):
    body = request.get_json(force=True) or {}
    allowed = {'name', 'description', 'speed_secs', 'enabled', 'media'}
    fields = {k: v for k, v in body.items() if k in allowed}
    if not fields:
        return jsonify({'success': False, 'error': 'No valid fields provided'}), 400
    updated = signage_config.update(name, fields)
    if not updated:
        return jsonify({'success': False, 'error': 'Slideshow not found'}), 404
    return jsonify({'success': True, 'config': updated})



# list all media files
@signage_bp.route('/api/media')
@access_required('signage')
def api_get_media():
    return jsonify({'success': True, 'media': media.get_all()})

# serve a media file
@signage_bp.route('/media/file/<path:filename>')
@access_required('signage')
def serve_media_file(filename):
    if not media.get_file(filename):
        return jsonify({'error': 'Not found'}), 404
    return send_from_directory(media.folder, filename)

# upload one or more media files
@signage_bp.route('/api/media/upload', methods=['POST'])
@access_required('signage')
def api_upload_media():
    files = request.files.getlist('files')
    if not files or all(f.filename == '' for f in files):
        return jsonify({'success': False, 'error': 'No files provided'}), 400
    results = []
    for f in files:
        if not f.filename:
            continue
        item = media.save_file(f)
        if item:
            results.append({'filename': item['filename'], 'success': True})
        else:
            results.append({'filename': f.filename, 'success': False, 'error': 'Invalid file type'})
    return jsonify({'success': True, 'results': results})

# slideshow config API (used by the player to poll for changes)
@signage_bp.route('/api/slideshow/<name>')
@login_required
def api_get_slideshow(name):
    slideshows = signage_config.get_all().get('slideshows', {})
    cfg = slideshows.get(name)
    if cfg is None:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    return jsonify({'success': True, 'config': cfg})

# delete a media file
@signage_bp.route('/api/media/delete/<path:filename>', methods=['POST'])
@access_required('signage')
def api_delete_media(filename):
    if not media.delete_file(filename):
        return jsonify({'success': False, 'error': 'Not found or invalid file type'}), 404
    signage_config.remove_media_from_all(filename)
    return jsonify({'success': True})

# fullscreen slideshow player
@signage_bp.route('/slideshow/<name>')
@login_required
def slideshow_view(name):
    slideshows = signage_config.get_all().get('slideshows', {})
    cfg = slideshows.get(name)
    if cfg is None:
        abort(404)
    return render_template('signage/slideshow.html', slideshow_key=name, cfg=cfg)

# ============================================================================
# Routes — status, logs, config
# ============================================================================

# get all logs and errors
@signage_bp.route('/api/logs')
@login_required
def api_get_logs():
    limit = request.args.get('limit', 50, type=int)
    logs = signage_log.get_logs(limit=limit)
    errors = signage_log.get_errors(limit=limit)
    return jsonify({'success': True, 'logs': logs, 'errors': errors})

# clear all logs
@signage_bp.route('/api/logs/clear', methods=['POST'])
@login_required
def api_clear_logs():
    count = signage_log.clear_logs()
    return jsonify({'success': True, 'count': count})

# clear all errors
@signage_bp.route('/api/errors/clear', methods=['POST'])
@login_required
def api_clear_errors():
    count = signage_log.clear_errors()
    return jsonify({'success': True, 'count': count})
