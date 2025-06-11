import json
import time
import logging
import threading
import os
from flask import current_app
os.makedirs('logs', exist_ok=True)
logging.basicConfig(filename='logs/stream_manager.log', level=logging.ERROR,
    format=
    '%(asctime)s - %(levelname)s - %(pathname)s:%(lineno)d - %(message)s')
logger = logging.getLogger(__name__)
stream_updates = {}
lock = threading.Lock()


def update_stream(user_id, dataset_id, operation_type, status, message,
    progress=0):
    try:
        key = str(user_id), operation_type
        logger.info(
            f'Attempting to update stream: user={user_id}, operation={operation_type}, status={status}, message={message}, progress={progress}'
            )
        with lock:
            if key not in stream_updates:
                stream_updates[key] = []
            update = {'status': status, 'message': message, 'progress':
                progress, 'timestamp': time.time()}
            stream_updates[key].append(update)
            logger.info(
                f'Stream update successful: user={user_id}, operation={operation_type}, status={status}, progress={progress}, updates_count={len(stream_updates[key])}'
                )
            return update
    except Exception as e:
        logger.error(f'Error updating stream: {str(e)}', exc_info=True)
        return None


def get_stream_updates(user_id, dataset_id, operation_type, last_index=0):
    try:
        key = str(user_id), operation_type
        logger.info(
            f'Getting updates for stream: user={user_id}, operation={operation_type}, last_index={last_index}'
            )
        with lock:
            updates = stream_updates.get(key, [])
            logger.info(
                f'Found {len(updates)} total updates, returning updates from index {last_index}'
                )
            if len(updates) > last_index:
                new_updates = updates[last_index:]
                logger.info(f'Returning {len(new_updates)} new updates')
                return new_updates, len(updates)
            else:
                logger.info('No new updates available')
                return [], last_index
    except Exception as e:
        logger.error(f'Error getting stream updates: {str(e)}', exc_info=True)
        return [], last_index


def clear_user_streams(user_id):
    try:
        with lock:
            keys_to_remove = [key for key in stream_updates.keys() if key[0
                ] == str(user_id)]
            for key in keys_to_remove:
                del stream_updates[key]
            logger.info(
                f'Cleared all streams for user {user_id}, removed {len(keys_to_remove)} stream(s)'
                )
    except Exception as e:
        logger.error(f'Error clearing user streams: {str(e)}', exc_info=True)


def clear_stream(user_id, operation_type):
    try:
        key = str(user_id), operation_type
        with lock:
            if key in stream_updates:
                del stream_updates[key]
                logger.info(
                    f'Cleared stream: user={user_id}, operation={operation_type}'
                    )
    except Exception as e:
        logger.error(f'Error clearing stream: {str(e)}', exc_info=True)


def cleanup_old_streams(max_age_seconds=300):
    try:
        with lock:
            current_time = time.time()
            keys_to_remove = []
            for key, updates in stream_updates.items():
                if not updates:
                    keys_to_remove.append(key)
                    continue
                last_update_time = updates[-1]['timestamp']
                if current_time - last_update_time > max_age_seconds:
                    keys_to_remove.append(key)
            for key in keys_to_remove:
                del stream_updates[key]
            if keys_to_remove:
                logger.info(f'Cleaned up {len(keys_to_remove)} old streams')
    except Exception as e:
        logger.error(f'Error cleaning up old streams: {str(e)}', exc_info=True)


def start_cleanup_scheduler(interval_seconds=60):

    def cleanup_task():
        while True:
            try:
                cleanup_old_streams()
                time.sleep(interval_seconds)
            except Exception as e:
                logger.error(f'Error in cleanup task: {str(e)}', exc_info=True)
                time.sleep(interval_seconds)
    cleanup_thread = threading.Thread(target=cleanup_task, daemon=True)
    cleanup_thread.start()
    logger.info(
        f'Started stream cleanup scheduler (interval: {interval_seconds}s)')
