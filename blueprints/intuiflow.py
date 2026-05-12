import base64
import io
import logging
import os
import threading
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Blueprint, jsonify, render_template, request

from API_Service_Network.Intuiflow.close_work_orders     import CloseWorkOrders
from API_Service_Network.Intuiflow.data                  import IntuiflowConfig, IntuiflowLog
from API_Service_Network.Intuiflow.import_pending_orders import ImportPendingOrders
from API_Service_Network.Intuiflow.update_work_orders    import UpdateWorkOrders
from API_Service_Network.Intuiflow.upload_fb_files       import UploadFbFiles
from blueprints.auth import access_required, login_required
from common.Clients.Email.EmailApi import send_email
from config import Config

intuiflow_bp = Blueprint('intuiflow', __name__)
logger = logging.getLogger(__name__)

# Instantiate data objects at module level
intuiflow_config = IntuiflowConfig()
intuiflow_log    = IntuiflowLog()

# Load and resize branded email images once at startup
def _load_img(filename: str, target_width: int = 600) -> str:
    from PIL import Image
    path = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'API_Service_Network',
                                         'src', 'common', 'Clients', 'Email', 'sources', filename))
    with Image.open(path) as img:
        w, h = img.size
        if w != target_width:
            new_h = round(h * target_width / w)
            img = img.resize((target_width, new_h), Image.LANCZOS)
        fmt = 'JPEG' if filename.lower().endswith('.jpg') else 'PNG'
        mime = 'image/jpeg' if fmt == 'JPEG' else 'image/png'
        buf = io.BytesIO()
        img.save(buf, format=fmt)
        return f'data:{mime};base64,' + base64.b64encode(buf.getvalue()).decode()

_HEADER_IMG = _load_img('radian_header.png')
_FOOTER_IMG = _load_img('radian_footer.jpg')

_PIPELINE_NAMES = {'full-sync', 'partial-sync'}
_pipeline_lock  = threading.Lock()  # one pipeline at a time; modules blocked while held
_ALL_NAMES = {
    'full-sync', 'partial-sync',
    'upload-fb-files', 'update-work-orders', 'close-work-orders', 'import-pending-orders',
}

# ============================================================================
# Notification helpers
# ============================================================================

def _email_wrap(title:str, subtitle:str, body_html:str) -> str:
    """Wrap email content with the Radian branded header and footer."""
    return f"""
<!DOCTYPE html>
<html xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <!--[if mso]><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch><o:AllowPNG/></o:OfficeDocumentSettings></xml><![endif]-->
  <style>
    body {{ margin:0; padding:0; background-color:#ffffff; font-family:'Helvetica Neue',Helvetica,Arial,sans-serif; -webkit-text-size-adjust:100%; -ms-text-size-adjust:100%; }}
    table {{ border-collapse:collapse; mso-table-lspace:0pt; mso-table-rspace:0pt; }}
    img {{ border:0; display:block; -ms-interpolation-mode:bicubic; }}
  </style>
</head>
<body style="margin:0;padding:0;background-color:#ffffff;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#ffffff">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" border="0" style="width:600px;">

        <!-- Header image -->
        <tr><td style="line-height:0;font-size:0;padding:0;"><img src="{_HEADER_IMG}" alt="Radian" width="600" style="display:block;width:600px;border:0;"></td></tr>

        <!-- Content card -->
        <tr><td style="background-color:#000000;padding:14px 32px 16px 32px;">

          <p style="margin:0 0 4px 0;font-size:11px;font-weight:700;letter-spacing:2px;
                     text-transform:uppercase;color:#6b7280;">INTUIFLOW</p>
          <h1 style="margin:0 0 16px 0;font-size:22px;font-weight:700;color:#FEC303;">{title}</h1>

          <p style="margin:0 0 20px 0;font-size:13px;color:#9ca3af;">{subtitle}</p>

          {body_html}

          <p style="margin:24px 0 0 0;mso-margin-bottom-alt:0;font-size:11px;color:#6b7280;border-top:1px solid #374151;padding-top:16px;">
            This is an automated notification from Radian Internal Services.
          </p>

        </td></tr>

        <!-- Footer image -->
        <tr><td style="padding:0;line-height:0;font-size:0;"><img src="{_FOOTER_IMG}" alt="" width="600" style="display:block;width:600px;border:0;"></td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

def _maybe_notify(cfg:dict, success:bool, log_data:dict) -> None:
    mode       = cfg.get('notify_mode', 'none')
    recipients = cfg.get('notify_recipients', [])
    if not recipients or mode == 'none':
        return
    if mode == 'failure' and success:
        return

    label        = cfg.get('label', 'Intuiflow')
    status_word  = 'Success' if success else 'Error'
    status_color = '#ffffff'
    status_bg    = "#2ed40d" if success else "#FE2003"
    subtitle     = f'Run completed at {datetime.now().strftime("%Y-%m-%d %H:%M")}'

    status_pill = (
        # Outlook Desktop: VML rounded rectangle (only way to get true pill shape in Word engine)
        f'<!--[if mso]>'
        f'<table cellpadding="0" cellspacing="0" border="0" style="margin-bottom:20px;">'
        f'<tr><td>'
        f'<v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" '
        f'arcsize="50%" fillcolor="{status_bg}" strokecolor="{status_bg}" '
        f'style="height:32px;v-text-anchor:middle;width:120px;">'
        f'<w:anchorlock/>'
        f'<p style="margin:0;text-align:center;color:{status_color};font-family:\'Helvetica Neue\',Helvetica,Arial,sans-serif;font-size:13px;font-weight:700;mso-margin-top-alt:0;mso-margin-bottom-alt:0;">{status_word}</p>'
        f'</v:roundrect>'
        f'</td></tr></table>'
        f'<![endif]-->'
        # Web clients: standard table with border-radius
        f'<!--[if !mso]><!-->'
        f'<table cellpadding="0" cellspacing="0" border="0" style="margin-bottom:20px;mso-table-lspace:0pt;mso-table-rspace:0pt;">'
        f'<tr><td style="background:{status_bg};padding:5px 16px;border-radius:9999px;">'
        f'<span style="color:{status_color};font-weight:700;font-size:12px;font-family:\'Helvetica Neue\',Helvetica,Arial,sans-serif;">{status_word}</span>'
        f'</td></tr></table>'
        f'<!--<![endif]-->'
    )

    log_sections = ''
    for module_label, funcs in log_data.items():
        if isinstance(funcs, list):
            # Fatal error: { "key: fatal": ["error string"] }
            msgs = ''.join(f'<li style="margin:2px 0;color:#9ca3af;">{m}</li>' for m in funcs)
            log_sections += (
                f'<p style="margin:0 0 4px 0;font-weight:700;font-size:13px;color:#FEC303;">{module_label}</p>'
                f'<ul style="margin:0 0 16px 0;padding-left:18px;list-style:disc;font-size:13px;">{msgs}</ul>'
            )
        else:
            # Nested: { "Module Label (STATUS)": { "Func Name": ["messages"] } }
            func_items = ''
            for func_name, messages in funcs.items():
                msg_list = ''.join(
                    f'<li style="margin:2px 0;color:#9ca3af;">{m}</li>' for m in messages
                )
                func_items += (
                    f'<li style="margin-bottom:12px;color:#ffffff;">'
                    f'<span style="font-weight:700;color:#ffffff;">{func_name}</span>'
                    f'<ul style="margin:4px 0 0 0;padding-left:18px;list-style:disc;">{msg_list}</ul>'
                    f'</li>'
                )
            log_sections += (
                f'<p style="margin:0 0 6px 0;font-weight:700;font-size:13px;color:#FEC303;">{module_label}</p>'
                f'<ol style="margin:0 0 16px 0;padding-left:20px;font-size:13px;line-height:1.6;">{func_items}</ol>'
            )

    body_html = status_pill + log_sections
    
    try:
        send_email(
            subject=f'{status_word} Summary Email: Intuiflow {label}',
            html_body=_email_wrap(label, subtitle, body_html),
            recipients=recipients,
            sender=Config.SENDER_EMAIL,
        )
    except Exception as e:
        logger.error(f'Notification email failed for {label}: {e}')

def _maybe_notify_short_inventory(cfg:dict, short_inventory:dict) -> None:
    if not short_inventory:
        return
    if not cfg.get('short_inv_notify_enabled'):
        return
    recipients = cfg.get('short_inv_notify_recipients', [])
    if not recipients:
        return
    
    status_word  = 'Error'
    status_color = '#ffffff'
    status_bg    = "#FE2003"

    status_pill = (
        # Outlook Desktop: VML rounded rectangle (only way to get true pill shape in Word engine)
        f'<!--[if mso]>'
        f'<table cellpadding="0" cellspacing="0" border="0" style="margin-bottom:20px;">'
        f'<tr><td>'
        f'<v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" '
        f'arcsize="50%" fillcolor="{status_bg}" strokecolor="{status_bg}" '
        f'style="height:32px;v-text-anchor:middle;width:120px;">'
        f'<w:anchorlock/>'
        f'<p style="margin:0;text-align:center;color:{status_color};font-family:\'Helvetica Neue\',Helvetica,Arial,sans-serif;font-size:13px;font-weight:700;mso-margin-top-alt:0;mso-margin-bottom-alt:0;">{status_word}</p>'
        f'</v:roundrect>'
        f'</td></tr></table>'
        f'<![endif]-->'
        # Web clients: standard table with border-radius
        f'<!--[if !mso]><!-->'
        f'<table cellpadding="0" cellspacing="0" border="0" style="margin-bottom:20px;mso-table-lspace:0pt;mso-table-rspace:0pt;">'
        f'<tr><td style="background:{status_bg};padding:5px 16px;border-radius:9999px;">'
        f'<span style="color:{status_color};font-weight:700;font-size:12px;font-family:\'Helvetica Neue\',Helvetica,Arial,sans-serif;">{status_word}</span>'
        f'</td></tr></table>'
        f'<!--<![endif]-->'
    )

    label    = cfg.get('label', 'Intuiflow')
    subtitle = (f'The following work orders were not closed due to short inventory '
                f'during the sync at {datetime.now().strftime("%Y-%m-%d %H:%M")}:')

    inv_items = ''
    for mo_num, messages in short_inventory.items():
        msg_list = ''.join(
            f'<li style="margin:2px 0;color:#9ca3af;">{m}</li>' for m in messages
        )
        inv_items += (
            f'<li style="margin-bottom:12px;color:#ffffff;">'
            f'<span style="font-weight:700;color:#ffffff;">Work Order: <b>{mo_num}</b></span>'
            f'<ul style="margin:4px 0 0 0;padding-left:18px;list-style:disc;">{msg_list}</ul>'
            f'</li>'
        )

    body_html = (status_pill + 
                 f'<ol style="margin:0;padding-left:20px;font-size:13px;line-height:1.6;color:#ffffff;">{inv_items}</ol>')

    try:
        send_email(
            subject=f'Short Inventory Alert - Failed to Close Order(s)',
            html_body=_email_wrap('Short Inventory Alert', subtitle, body_html),
            recipients=recipients,
            sender=Config.SENDER_EMAIL,
        )
    except Exception as e:
        logger.error(f'Short inventory notification email failed for {label}: {e}')

def _maybe_notify_def_locations(cfg:dict, def_locations:dict):
    if not def_locations:
        return
    if not cfg.get('def_locations_notify_enabled'):
        return
    recipients = cfg.get('def_locations_notify_recipients', [])
    if not recipients:
        return
    
    status_word  = 'Error'
    status_color = '#ffffff'
    status_bg    = "#FE2003"

    status_pill = (
        # Outlook Desktop: VML rounded rectangle (only way to get true pill shape in Word engine)
        f'<!--[if mso]>'
        f'<table cellpadding="0" cellspacing="0" border="0" style="margin-bottom:20px;">'
        f'<tr><td>'
        f'<v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" '
        f'arcsize="50%" fillcolor="{status_bg}" strokecolor="{status_bg}" '
        f'style="height:32px;v-text-anchor:middle;width:120px;">'
        f'<w:anchorlock/>'
        f'<p style="margin:0;text-align:center;color:{status_color};font-family:\'Helvetica Neue\',Helvetica,Arial,sans-serif;font-size:13px;font-weight:700;mso-margin-top-alt:0;mso-margin-bottom-alt:0;">{status_word}</p>'
        f'</v:roundrect>'
        f'</td></tr></table>'
        f'<![endif]-->'
        # Web clients: standard table with border-radius
        f'<!--[if !mso]><!-->'
        f'<table cellpadding="0" cellspacing="0" border="0" style="margin-bottom:20px;mso-table-lspace:0pt;mso-table-rspace:0pt;">'
        f'<tr><td style="background:{status_bg};padding:5px 16px;border-radius:9999px;">'
        f'<span style="color:{status_color};font-weight:700;font-size:12px;font-family:\'Helvetica Neue\',Helvetica,Arial,sans-serif;">{status_word}</span>'
        f'</td></tr></table>'
        f'<!--<![endif]-->'
    )

    label    = cfg.get('label', 'Intuiflow')
    subtitle = (f'The following work orders were not closed due to missing/invalid default locations '
                f'on their parts during the sync at {datetime.now().strftime("%Y-%m-%d %H:%M")}:')

    vals = ''
    for mo_num, messages in def_locations.items():
        msg_list = ''.join(
            f'<li style="margin:2px 0;color:#9ca3af;">{m}</li>' for m in messages
        )
        vals += (
            f'<li style="margin-bottom:12px;color:#ffffff;">'
            f'<span style="font-weight:700;color:#ffffff;">Work Order: <b>{mo_num}</b></span>'
            f'<ul style="margin:4px 0 0 0;padding-left:18px;list-style:disc;">{msg_list}</ul>'
            f'</li>'
        )

    body_html = (status_pill + 
                 f'<ol style="margin:0;padding-left:20px;font-size:13px;line-height:1.6;color:#ffffff;">{vals}</ol>')

    try:
        send_email(
            subject=f'Invalid Default Location Alert - Failed to Close Order(s)',
            html_body=_email_wrap('Default Location Alert', subtitle, body_html),
            recipients=recipients,
            sender=Config.SENDER_EMAIL,
        )
    except Exception as e:
        logger.error(f'Invalid default location notification email failed for {label}: {e}')

# ============================================================================
# Runner functions
# Called directly by APScheduler and by /run/<name> routes (via a thread).
# ============================================================================

def run_full_sync(triggered_by:str='scheduler') -> None:
    _pipeline_lock.acquire()  # blocking — waits if partial-sync is running
    try:
        intuiflow_config.set_running('full-sync', True)
        cfg               = intuiflow_config.get('full-sync')
        short_inventory   = {}
        default_locations = {}
        combined_log      = {}
        all_success       = True

        try:
            log_obj = ImportPendingOrders().auto_run()
            if log_obj.error_flag() != 0:
                combined_log["Import Pending Orders to Fishbowl (ISSUES)"] = log_obj.get_log()
                all_success = False
            else:
                combined_log["Import Pending Orders to Fishbowl (SUCCESS)"] = log_obj.get_log()
        except Exception as e:
            all_success = False
            combined_log['import-pending-orders: fatal'] = [str(e)]
            logger.error(f'full-sync: import-pending-orders failed: {e}')

        try:
            log_obj = UpdateWorkOrders().auto_run()
            if log_obj.error_flag() != 0:
                combined_log["Update Fishbowl WO Data (ISSUES)"] = log_obj.get_log()
                all_success = False
            else:
                combined_log["Update Fishbowl WO Data (SUCCESS)"] = log_obj.get_log()
        except Exception as e:
            all_success = False
            combined_log['update-work-orders: fatal'] = [str(e)]
            logger.error(f'full-sync: update-work-orders failed: {e}')

        try:
            module            = CloseWorkOrders()
            log_obj           = module.auto_run()
            short_inventory   = module.short_inventory or {}
            default_locations = module.default_location or {}
            if log_obj.error_flag() != 0:
                combined_log["Close Fishbowl WOs (ISSUES)"] = log_obj.get_log()
                all_success = False
            else:
                combined_log["Close Fishbowl WOs (SUCCESS)"] = log_obj.get_log()
        except Exception as e:
            all_success = False
            combined_log['close-work-orders: fatal'] = [str(e)]
            logger.error(f'full-sync: close-work-orders failed: {e}')

        try:
            log_obj = UploadFbFiles().auto_run()
            if log_obj.error_flag() != 0:
                combined_log["File Upload to Intuiflow (ISSUES)"] = log_obj.get_log()
                all_success = False
            else:
                combined_log["File Upload to Intuiflow (SUCCESS)"] = log_obj.get_log()
        except Exception as e:
            all_success = False
            combined_log['upload-fb-files: fatal'] = [str(e)]
            logger.error(f'full-sync: upload-fb-files failed: {e}')

        intuiflow_config.save_result('full-sync', all_success)
        intuiflow_log.append_run('full-sync', 'success' if all_success else 'error', triggered_by, combined_log)
        _maybe_notify(cfg, all_success, combined_log)
        _maybe_notify_short_inventory(cfg, short_inventory)
        _maybe_notify_def_locations(cfg, default_locations)
    finally:
        _pipeline_lock.release()

def run_partial_sync(triggered_by:str='scheduler') -> None:
    _pipeline_lock.acquire()  # blocking — waits if full-sync is running
    try:
        intuiflow_config.set_running('partial-sync', True)
        cfg               = intuiflow_config.get('partial-sync')
        short_inventory   = {}
        default_locations = {}
        combined_log      = {}
        all_success       = True

        try:
            log_obj = UpdateWorkOrders().auto_run()
            if log_obj.error_flag() != 0:
                combined_log["Update Fishbowl WO Data (ISSUES)"] = log_obj.get_log()
                all_success = False
            else:
                combined_log["Update Fishbowl WO Data (SUCCESS)"] = log_obj.get_log()
        except Exception as e:
            all_success = False
            combined_log['update-work-orders: fatal'] = [str(e)]
            logger.error(f'partial-sync: update-work-orders failed: {e}')

        try:
            module            = CloseWorkOrders()
            log_obj           = module.auto_run()
            short_inventory   = module.short_inventory or {}
            default_locations = module.default_location or {}
            if log_obj.error_flag() != 0:
                combined_log["Close Fishbowl WOs (ISSUES)"] = log_obj.get_log()
                all_success = False
            else:
                combined_log["Close Fishbowl WOs (SUCCESS)"] = log_obj.get_log()
        except Exception as e:
            all_success = False
            combined_log['close-work-orders: fatal'] = [str(e)]
            logger.error(f'partial-sync: close-work-orders failed: {e}')

        intuiflow_config.save_result('partial-sync', all_success)
        intuiflow_log.append_run('partial-sync', 'success' if all_success else 'error', triggered_by, combined_log)
        _maybe_notify(cfg, all_success, combined_log)
        _maybe_notify_short_inventory(cfg, short_inventory)
        _maybe_notify_def_locations(cfg, default_locations)
    finally:
        _pipeline_lock.release()

def run_upload_fb_files(triggered_by:str='manual') -> None:
    if not _pipeline_lock.acquire(blocking=False):
        logger.info('upload-fb-files blocked: a sync pipeline is currently running')
        return
    try:
        intuiflow_config.set_running('upload-fb-files', True)
        cfg = intuiflow_config.get('upload-fb-files')
        try:
            log_obj    = UploadFbFiles().auto_run()
            is_success = log_obj.error_flag() == 0
            log_data   = {"File Upload to Intuiflow": log_obj.get_log()}
        except Exception as e:
            is_success, log_data = False, {'error': [str(e)]}
            logger.error(f'upload-fb-files failed: {e}')
        intuiflow_config.save_result('upload-fb-files', is_success)
        intuiflow_log.append_run('upload-fb-files', 'success' if is_success else 'error', triggered_by, log_data)
        _maybe_notify(cfg, is_success, log_data)
    finally:
        _pipeline_lock.release()

def run_update_work_orders(triggered_by:str='manual') -> None:
    if not _pipeline_lock.acquire(blocking=False):
        logger.info('update-work-orders blocked: a sync pipeline is currently running')
        return
    try:
        intuiflow_config.set_running('update-work-orders', True)
        cfg = intuiflow_config.get('update-work-orders')
        try:
            log_obj    = UpdateWorkOrders().auto_run()
            is_success = log_obj.error_flag() == 0
            log_data   = {"Update Fishbowl WO Data": log_obj.get_log()}
        except Exception as e:
            is_success, log_data = False, {'error': [str(e)]}
            logger.error(f'update-work-orders failed: {e}')
        intuiflow_config.save_result('update-work-orders', is_success)
        intuiflow_log.append_run('update-work-orders', 'success' if is_success else 'error', triggered_by, log_data)
        _maybe_notify(cfg, is_success, log_data)
    finally:
        _pipeline_lock.release()

def run_close_work_orders(triggered_by:str='manual') -> None:
    if not _pipeline_lock.acquire(blocking=False):
        logger.info('close-work-orders blocked: a sync pipeline is currently running')
        return
    try:
        intuiflow_config.set_running('close-work-orders', True)
        cfg             = intuiflow_config.get('close-work-orders')
        short_inventory = {}
        try:
            module          = CloseWorkOrders()
            log_obj         = module.auto_run()
            short_inventory = module.short_inventory or {}
            is_success      = log_obj.error_flag() == 0
            log_data        = {"Close Fishbowl WOs": log_obj.get_log()}
        except Exception as e:
            is_success, log_data = False, {'error': [str(e)]}
            logger.error(f'close-work-orders failed: {e}')
        intuiflow_config.save_result('close-work-orders', is_success)
        intuiflow_log.append_run('close-work-orders', 'success' if is_success else 'error', triggered_by, log_data)
        _maybe_notify(cfg, is_success, log_data)
        _maybe_notify_short_inventory(cfg, short_inventory)
    finally:
        _pipeline_lock.release()

def run_import_pending_orders(triggered_by:str='manual') -> None:
    if not _pipeline_lock.acquire(blocking=False):
        logger.info('import-pending-orders blocked: a sync pipeline is currently running')
        return
    try:
        intuiflow_config.set_running('import-pending-orders', True)
        cfg = intuiflow_config.get('import-pending-orders')
        try:
            log_obj    = ImportPendingOrders().auto_run()
            is_success = log_obj.error_flag() == 0
            log_data   = {"Import Pending Orders to Fishbowl": log_obj.get_log()}
        except Exception as e:
            is_success, log_data = False, {'error': [str(e)]}
            logger.error(f'import-pending-orders failed: {e}')
        intuiflow_config.save_result('import-pending-orders', is_success)
        intuiflow_log.append_run('import-pending-orders', 'success' if is_success else 'error', triggered_by, log_data)
        _maybe_notify(cfg, is_success, log_data)
    finally:
        _pipeline_lock.release()


_RUNNERS = {
    'full-sync':             run_full_sync,
    'partial-sync':          run_partial_sync,
    'upload-fb-files':       run_upload_fb_files,
    'update-work-orders':    run_update_work_orders,
    'close-work-orders':     run_close_work_orders,
    'import-pending-orders': run_import_pending_orders,
}

# ============================================================================
# Scheduler — pipelines only
# ============================================================================

scheduler = BackgroundScheduler()


def _schedule(name: str, cfg: dict) -> None:
    """Add or replace the APScheduler job for a pipeline. No-op if not enabled."""
    if name not in _PIPELINE_NAMES:
        return
    runner = _RUNNERS.get(name)
    if not runner:
        return

    job_id = f'job_intuiflow_{name}'
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    if not cfg.get('enabled'):
        return

    if cfg.get('schedule_type') == 'cron' and cfg.get('schedule_cron'):
        scheduler.add_job(
            func=runner,
            trigger='cron',
            id=job_id,
            replace_existing=True,
            **cfg['schedule_cron'],
        )
    else:
        start_date = None
        if cfg.get('last_run'):
            try:
                start_date = datetime.fromisoformat(cfg['last_run'])
            except (ValueError, TypeError):
                pass
        scheduler.add_job(
            func=runner,
            trigger='interval',
            minutes=cfg.get('schedule_interval_minutes', 1440),
            start_date=start_date,
            id=job_id,
            replace_existing=True,
        )
    logger.info(f"Scheduled intuiflow {name} (type={cfg.get('schedule_type', 'interval')})")


# On startup, restore schedules for enabled pipelines.
for _name, _cfg in intuiflow_config.get_all().items():
    if _name in _PIPELINE_NAMES and _cfg.get('enabled'):
        _schedule(_name, _cfg)

if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or os.environ.get('PRODUCTION') == '1':
    scheduler.start()


# ============================================================================
# Routes — page
# ============================================================================

@intuiflow_bp.route('/')
@access_required('intuiflow')
def index():
    config = intuiflow_config.get_all()
    return render_template('intuiflow/index.html', config=config)


@intuiflow_bp.route('/how-to')
@access_required('intuiflow')
def how_to():
    return render_template('intuiflow/how_to.html')


# ============================================================================
# Routes — run, status, logs, config
# ============================================================================

@intuiflow_bp.route('/run/<name>', methods=['POST'])
@login_required
def run_now(name):
    if name not in _ALL_NAMES:
        return jsonify({'error': 'Unknown name'}), 404
    cfg = intuiflow_config.get(name)
    if cfg.get('running'):
        return jsonify({'error': f'{cfg["label"]} is already running'}), 409
    if name not in _PIPELINE_NAMES:
        full_cfg    = intuiflow_config.get('full-sync')
        partial_cfg = intuiflow_config.get('partial-sync')
        if full_cfg.get('running') or partial_cfg.get('running'):
            return jsonify({'error': 'A sync pipeline is currently running. Individual modules cannot be started until it completes.'}), 409
    runner = _RUNNERS[name]
    threading.Thread(target=runner, kwargs={'triggered_by': 'manual'}, daemon=True).start()
    return jsonify({'success': True, 'message': f'{cfg["label"]} started'})


@intuiflow_bp.route('/status', methods=['GET'])
@login_required
def get_status():
    config = intuiflow_config.get_all()
    for name, cfg in config.items():
        if name in _PIPELINE_NAMES:
            job = scheduler.get_job(f'job_intuiflow_{name}')
            cfg['next_run'] = job.next_run_time.isoformat() if job and job.next_run_time else None
        else:
            cfg['next_run'] = None
    return jsonify({'success': True, 'config': config})


@intuiflow_bp.route('/logs/<name>', methods=['GET'])
@login_required
def get_logs(name):
    if name not in _ALL_NAMES:
        return jsonify({'error': 'Unknown name'}), 404
    return jsonify({'success': True, 'data': intuiflow_log.get_logs(name)})


@intuiflow_bp.route('/logs/<name>', methods=['DELETE'])
@login_required
def clear_logs(name):
    if name not in _ALL_NAMES:
        return jsonify({'error': 'Unknown name'}), 404
    count = intuiflow_log.clear_logs(name)
    return jsonify({'success': True, 'cleared': count})


@intuiflow_bp.route('/logs/<name>/errors', methods=['DELETE'])
@login_required
def clear_errors(name):
    if name not in _ALL_NAMES:
        return jsonify({'error': 'Unknown name'}), 404
    count = intuiflow_log.clear_errors(name)
    return jsonify({'success': True, 'cleared': count})


@intuiflow_bp.route('/config/<name>', methods=['PUT'])
@login_required
def update_config(name):
    try:
        if name not in _ALL_NAMES:
            return jsonify({'error': 'Unknown name'}), 404

        req_data = request.get_json()
        updates  = {}

        # --- Schedule fields (pipelines only) ---
        if name in _PIPELINE_NAMES:
            if 'schedule_type' in req_data:
                updates['schedule_type'] = req_data['schedule_type']
            if 'schedule_interval_minutes' in req_data:
                interval = int(req_data['schedule_interval_minutes'])
                if interval < 1:
                    return jsonify({'error': 'Interval must be at least 1 minute'}), 400
                updates['schedule_interval_minutes'] = interval
            if 'schedule_cron' in req_data:
                updates['schedule_cron'] = req_data['schedule_cron']
            if 'enabled' in req_data:
                updates['enabled'] = bool(req_data['enabled'])

        # --- Standard notification fields ---
        if 'notify_mode' in req_data:
            if req_data['notify_mode'] not in ('none', 'always', 'failure'):
                return jsonify({'error': 'Invalid notify_mode'}), 400
            updates['notify_mode'] = req_data['notify_mode']
        if 'notify_recipients' in req_data:
            updates['notify_recipients'] = list(req_data['notify_recipients'])

        # --- Additional notification fields (pipelines + close-work-orders) ---
        if name in _PIPELINE_NAMES or name == 'close-work-orders':
            # --- Short inventory notification fields
            if 'short_inv_notify_enabled' in req_data:
                updates['short_inv_notify_enabled'] = bool(req_data['short_inv_notify_enabled'])
            if 'short_inv_notify_recipients' in req_data:
                updates['short_inv_notify_recipients'] = list(req_data['short_inv_notify_recipients'])
            # --- Invalid default location notification fields
            if 'def_loc_notify_enabled' in req_data:
                updates['def_locations_notify_enabled'] = bool(req_data['def_loc_notify_enabled'])
            if 'def_loc_notify_recipients' in req_data:
                updates['def_locations_notify_recipients'] = list(req_data['def_loc_notify_recipients'])

        updated = intuiflow_config.update(name, updates)

        if name in _PIPELINE_NAMES:
            _schedule(name, updated)
            job = scheduler.get_job(f'job_intuiflow_{name}')
            updated['next_run'] = job.next_run_time.isoformat() if job and job.next_run_time else None
        else:
            updated['next_run'] = None

        return jsonify({'success': True, 'config': updated})

    except Exception as e:
        logger.error(f'Error updating config for {name}: {e}')
        return jsonify({'error': str(e)}), 500
