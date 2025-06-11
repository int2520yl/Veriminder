from flask import Blueprint, Response, stream_with_context, session, request
import json
import time
import logging
import os
import traceback
from . import stream_manager
import json
import os
os.makedirs('logs', exist_ok=True)
logging.basicConfig(filename='logs/streaming_service.log', level=logging.
    ERROR, format=
    '%(asctime)s - %(levelname)s - %(pathname)s:%(lineno)d - %(message)s')
logger = logging.getLogger(__name__)
bp = Blueprint('streaming', __name__, url_prefix='/api/stream')


def get_friendly_message(operation, status='starting'):
    try:
        messages_file = os.path.join(os.path.dirname(__file__), '..',
            'resources', 'streaming_messages.json')
        if os.path.exists(messages_file):
            with open(messages_file, 'r') as f:
                messages = json.load(f)
            if operation in messages and status in messages[operation]:
                return messages[operation][status]['message']
    except Exception as e:
        logger.warning(f'Failed to load friendly message: {str(e)}')
    return f'Starting {operation} process...'


@bp.route('/<operation>/<dataset_id>', methods=['GET'])
def stream_updates(operation, dataset_id):
    try:
        user_id = session.get('user_id')
        if not user_id:
            logger.warning(
                f'Stream request without user_id in session: {operation}, {dataset_id}'
                )
            return Response('No user session', status=400)
        logger.info(
            f'Starting stream for: user={user_id}, dataset={dataset_id}, operation={operation}'
            )
        try:
            dataset_id = int(dataset_id)
        except ValueError:
            if dataset_id.startswith('temp_'):
                logger.info(f'Using temporary dataset ID: {dataset_id}')
            else:
                logger.error(f'Invalid dataset_id: {dataset_id}')
                return Response('Invalid dataset ID', status=400)
        stream_manager.update_stream(user_id, dataset_id, operation,
            'starting', f'Initializing {operation} process...', 0)

        def generate():
            logger.info(
                f'SSE connection generator started for: user={user_id}, dataset={dataset_id}, operation={operation}'
                )
            yield 'retry: 1000\n'
            yield 'event: connected\ndata: {"status": "connected"}\n\n'
            logger.info(
                f'SSE initial event sent for: user={user_id}, dataset={dataset_id}, operation={operation}'
                )
            last_index = 0
            retry_count = 0
            max_retries = 120
            yield ' ' * 2048 + '\n\n'
            while retry_count < max_retries:
                new_updates, last_index = stream_manager.get_stream_updates(
                    user_id, dataset_id, operation, last_index)
                if new_updates:
                    for update in new_updates:
                        event_data = json.dumps(update)
                        logger.info(f'Sending event: {event_data[:100]}...')
                        yield f'data: {event_data}\n\n'
                        yield f': padding {time.time()}\n\n'
                    retry_count = 0
                    last_update = new_updates[-1]
                    if last_update['status'] in ['complete', 'error']:
                        logger.info(
                            f'Sending close event for: user={user_id}, dataset={dataset_id}, operation={operation}'
                            )
                        yield f"event: close\ndata: {json.dumps({'status': 'closed'})}\n\n"
                        break
                else:
                    retry_count += 1
                time.sleep(0.1)
            if retry_count >= max_retries:
                logger.warning(
                    f'Stream timeout: user={user_id}, dataset={dataset_id}, operation={operation}'
                    )
                yield f"event: close\ndata: {json.dumps({'status': 'timeout'})}\n\n"
            logger.info(
                f'Stream generator finished for: user={user_id}, dataset={dataset_id}, operation={operation}'
                )
        response = Response(stream_with_context(generate()), mimetype=
            'text/event-stream', headers={'Cache-Control':
            'no-cache, no-transform, must-revalidate', 'X-Accel-Buffering':
            'no', 'Connection': 'keep-alive', 'Transfer-Encoding':
            'chunked', 'Content-Type': 'text/event-stream; charset=utf-8'})
        logger.info(
            f'Returning streaming response for: user={user_id}, dataset={dataset_id}, operation={operation}'
            )
        return response
    except Exception as e:
        logger.error(f'Stream error: {str(e)}')
        logger.error(traceback.format_exc())
        return Response('Stream error', status=500)


@bp.route('/cancel/<operation>/<dataset_id>', methods=['POST'])
def cancel_stream(operation, dataset_id):
    try:
        user_id = session.get('user_id')
        if not user_id:
            return {'success': False, 'error': 'No user session'}, 400
        try:
            dataset_id = int(dataset_id)
        except ValueError:
            return {'success': False, 'error': 'Invalid dataset ID'}, 400
        stream_manager.update_stream(user_id, dataset_id, operation,
            'cancelled', 'Operation cancelled by user', 100)
        stream_manager.clear_stream(user_id, dataset_id, operation)
        logger.info(
            f'Stream cancelled: user={user_id}, dataset={dataset_id}, operation={operation}'
            )
        return {'success': True, 'message': 'Stream cancelled'}
    except Exception as e:
        logger.error(f'Cancel stream error: {str(e)}')
        logger.error(traceback.format_exc())
        return {'success': False, 'error': str(e)}, 500
