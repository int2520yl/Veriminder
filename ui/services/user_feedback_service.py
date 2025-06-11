from flask import Blueprint, request, jsonify, current_app, session
import json
import logging
import mysql.connector
import os
from datetime import datetime
os.makedirs('logs', exist_ok=True)
logging.basicConfig(filename='logs/user_feedback_service.log', level=
    logging.INFO, format=
    '%(asctime)s - %(levelname)s - %(pathname)s:%(lineno)d - %(message)s')
logger = logging.getLogger(__name__)
bp = Blueprint('user_feedback', __name__, url_prefix='/api/user_feedback')
DB_CONFIG = {
    'host': 'YOUR_DATABASE_HOST',
    'port': 'YOUR_DATABASE_POST',
    'user': 'YOUR_DATABASE_USER',
    'password': 'YOUR_DATABASE_PASSWORD',
    'database': 'YOUR_DATABASE_NAME'
}



def get_db_connection():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except mysql.connector.Error as e:
        logger.error(f'Database connection error: {str(e)}')
        raise


@bp.route('/', methods=['POST'])
@bp.route('/', methods=['POST'])
def submit_feedback():
    try:
        feedback_data = request.json
        logger.info(f'Received feedback data: {json.dumps(feedback_data)}')
        required_fields = ['dataset_id', 'user_id', 'scenario_realism',
            'suggestion_effectiveness', 'rationale_clarity', 'question_impact']
        for field in required_fields:
            if field not in feedback_data or feedback_data[field] is None:
                logger.error(f'Missing required field: {field}')
                return jsonify({'success': False, 'error':
                    f'Missing required field: {field}'}), 400
        try:
            dataset_id = int(feedback_data['dataset_id'])
            user_id = int(feedback_data['user_id'])
        except (ValueError, TypeError) as e:
            logger.error(f'Type conversion error: {str(e)}')
            return jsonify({'success': False, 'error':
                f'Invalid ID format: {str(e)}'}), 400
        solution_score = {'scenario_realism': int(feedback_data[
            'scenario_realism']), 'suggestion_effectiveness': int(
            feedback_data['suggestion_effectiveness']), 'rationale_clarity':
            int(feedback_data['rationale_clarity']), 'question_impact': int
            (feedback_data['question_impact']), 'submission_time': datetime
            .now().strftime('%Y-%m-%d %H:%M:%S')}
        logger.info(
            f'Preparing to save solution_score: {json.dumps(solution_score)}')
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT id FROM level_1_evaluation WHERE dataset_id = %s AND user_id = %s'
            , (dataset_id, user_id))
        existing_entry = cursor.fetchone()
        if existing_entry:
            logger.info(
                f'Updating existing entry for dataset_id {dataset_id}, user_id {user_id}'
                )
            cursor.execute(
                'UPDATE level_1_evaluation SET solution_score = %s WHERE dataset_id = %s AND user_id = %s'
                , (json.dumps(solution_score), dataset_id, user_id))
        else:
            logger.info(
                f'Inserting new entry for dataset_id {dataset_id}, user_id {user_id}'
                )
            cursor.execute(
                'INSERT INTO level_1_evaluation (dataset_id, user_id, solution_score, status, ui_version) VALUES (%s, %s, %s, %s, %s)'
                , (dataset_id, user_id, json.dumps(solution_score),
                'active', 1))
        conn.commit()
        logger.info('Database transaction committed successfully')
        cursor.close()
        conn.close()
        return jsonify({'success': True, 'message':
            'Feedback submitted successfully'}), 200
    except Exception as e:
        logger.error(f'Error submitting feedback: {str(e)}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
