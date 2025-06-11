from flask import Blueprint, request, jsonify, session, render_template, redirect, url_for, flash
import json
import logging
import mysql.connector
import os
from datetime import datetime
os.makedirs('logs', exist_ok=True)
logging.basicConfig(filename='logs/analyst_feedback_service.log', level=
    logging.INFO, format=
    '%(asctime)s - %(levelname)s - %(pathname)s:%(lineno)d - %(message)s')
logger = logging.getLogger(__name__)
bp = Blueprint('analyst_feedback_service', __name__, url_prefix=
    '/api/analyst_feedback')
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


@bp.route('/dashboard', methods=['GET'])
def dashboard():
    user_id = session.get('user_id')
    if not user_id:
        flash('Please login first.', 'warning')
        return redirect(url_for('analyst_interface.index'))
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT ud.id, ud.dataset_id, d.decision,
                   ud.model_1_questions, ud.model_2_questions, ud.model_3_questions, 
                   ud.model_4_questions, ud.model_5_questions,
                   CASE 
                       WHEN ud.assigned_user_id_1 = %s THEN ud.user_id_1_score
                       WHEN ud.assigned_user_id_2 = %s THEN ud.user_id_2_score
                       WHEN ud.assigned_user_id_3 = %s THEN ud.user_id_3_score
                       WHEN ud.assigned_user_id_4 = %s THEN ud.user_id_4_score
                   END as user_score
            FROM user_type_2_evaluation_dataset ud
            JOIN dataset d ON ud.dataset_id = d.id
            WHERE (ud.assigned_user_id_1 = %s OR ud.assigned_user_id_2 = %s OR 
                   ud.assigned_user_id_3 = %s OR ud.assigned_user_id_4 = %s)
            AND ud.status = 'active'
        """
            , (user_id, user_id, user_id, user_id, user_id, user_id,
            user_id, user_id))
        assigned_evaluations = cursor.fetchall()
        cursor.close()
        evaluations = []
        for eval_data in assigned_evaluations:
            decision_json = json.loads(eval_data['decision']) if eval_data[
                'decision'] else {}
            decision_text = decision_json.get('text',
                'No decision text available')
            models_data = {}
            for i in range(1, 6):
                model_key = f'model_{i}_questions'
                if eval_data[model_key]:
                    try:
                        models_data[f'model_{i}'] = json.loads(eval_data[
                            model_key])
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(
                            f"Failed to parse model questions JSON for dataset {eval_data['dataset_id']}, model {i}"
                            )
                        models_data[f'model_{i}'] = []
            is_completed = eval_data['user_score'] is not None
            score_data = None
            if is_completed and eval_data['user_score']:
                try:
                    score_data = json.loads(eval_data['user_score'])
                except (json.JSONDecodeError, TypeError):
                    logger.warning(
                        f"Failed to parse user score JSON for dataset {eval_data['dataset_id']}"
                        )
            evaluations.append({'id': eval_data['id'], 'dataset_id':
                eval_data['dataset_id'], 'decision_text': decision_text,
                'models_data': models_data, 'is_completed': is_completed,
                'score_data': score_data})
        all_completed = len(evaluations) > 0 and all(eval_data[
            'is_completed'] for eval_data in evaluations)
        return render_template('data_analyst.html', evaluations=evaluations,
            all_completed=all_completed, user_id=user_id)
    except Exception as e:
        logger.error(f'Error loading analyst dashboard: {str(e)}')
        flash('An error occurred while loading your assignments.', 'danger')
        return redirect(url_for('analyst_interface.index'))
    finally:
        if conn:
            conn.close()


@bp.route('/submit', methods=['POST'])
def submit_feedback():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'User not logged in'}), 401
    try:
        feedback_data = request.json
        logger.info(f'Received analyst feedback data')
        required_fields = ['evaluation_id', 'ratings']
        for field in required_fields:
            if field not in feedback_data:
                logger.error(f'Missing required field: {field}')
                return jsonify({'success': False, 'error':
                    f'Missing required field: {field}'}), 400
        evaluation_id = feedback_data['evaluation_id']
        ratings = feedback_data['ratings']
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT 
                CASE 
                    WHEN assigned_user_id_1 = %s THEN 1
                    WHEN assigned_user_id_2 = %s THEN 2
                    WHEN assigned_user_id_3 = %s THEN 3
                    WHEN assigned_user_id_4 = %s THEN 4
                    ELSE NULL
                END as user_slot
            FROM user_type_2_evaluation_dataset
            WHERE id = %s
        """
            , (user_id, user_id, user_id, user_id, evaluation_id))
        slot_result = cursor.fetchone()
        if not slot_result or not slot_result['user_slot']:
            cursor.close()
            conn.close()
            logger.error(
                f'User {user_id} not assigned to evaluation {evaluation_id}')
            return jsonify({'success': False, 'error':
                'User not assigned to this evaluation'}), 403
        user_slot = slot_result['user_slot']
        score_field = f'user_id_{user_slot}_score'
        score_data = {'ratings': ratings, 'timestamp': datetime.now().
            strftime('%Y-%m-%d %H:%M:%S')}
        try:
            cursor.execute(
                f'UPDATE user_type_2_evaluation_dataset SET {score_field} = %s WHERE id = %s'
                , (json.dumps(score_data), evaluation_id))
            conn.commit()
            logger.info(
                f'User {user_id} submitted feedback for evaluation {evaluation_id}'
                )
        except Exception as e:
            logger.error(f'Error updating evaluation: {str(e)}')
            conn.rollback()
            return jsonify({'success': False, 'error':
                f'Database error: {str(e)}'}), 500
        finally:
            cursor.close()
            conn.close()
        all_completed = check_user_completed_all(user_id)
        if all_completed:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE test_user SET user_status = 'completed' WHERE id = %s"
                    , (user_id,))
                conn.commit()
                cursor.close()
                conn.close()
                logger.info(
                    f"User {user_id} completed all evaluations, status updated to 'completed'"
                    )
            except Exception as e:
                logger.error(f'Error updating user status: {str(e)}')
        return jsonify({'success': True, 'message':
            'Feedback submitted successfully', 'all_completed':
            all_completed, 'completion_code': None})
    except Exception as e:
        logger.error(f'Error submitting feedback: {str(e)}')
        return jsonify({'success': False, 'error': str(e)}), 500


def check_user_completed_all(user_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT COUNT(*) as total_assignments
            FROM user_type_2_evaluation_dataset
            WHERE (assigned_user_id_1 = %s OR assigned_user_id_2 = %s OR 
                assigned_user_id_3 = %s OR assigned_user_id_4 = %s)
            AND status = 'active'
        """
            , (user_id, user_id, user_id, user_id))
        total_result = cursor.fetchone()
        total_assignments = total_result['total_assignments'
            ] if total_result else 0
        cursor.execute(
            """
            SELECT COUNT(*) as completed_assignments
            FROM user_type_2_evaluation_dataset ud
            WHERE ((assigned_user_id_1 = %s AND user_id_1_score IS NOT NULL) OR
                (assigned_user_id_2 = %s AND user_id_2_score IS NOT NULL) OR
                (assigned_user_id_3 = %s AND user_id_3_score IS NOT NULL) OR
                (assigned_user_id_4 = %s AND user_id_4_score IS NOT NULL))
            AND status = 'active'
        """
            , (user_id, user_id, user_id, user_id))
        completed_result = cursor.fetchone()
        completed_assignments = completed_result['completed_assignments'
            ] if completed_result else 0
        cursor.close()
        conn.close()
        return (total_assignments > 0 and completed_assignments >=
            total_assignments)
    except Exception as e:
        logger.error(f'Error checking user completion status: {str(e)}')
        if conn:
            conn.close()
        return False


@bp.route('/status', methods=['GET'])
def get_status():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'User not logged in'}), 401
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT COUNT(*) as total
            FROM user_type_2_evaluation_dataset
            WHERE (
                assigned_user_id_1 = %s OR
                assigned_user_id_2 = %s OR
                assigned_user_id_3 = %s OR
                assigned_user_id_4 = %s
            )
            AND status = 'active'
        """
            , (user_id, user_id, user_id, user_id))
        total_result = cursor.fetchone()
        total = total_result['total'] if total_result else 0
        cursor.execute(
            """
            SELECT COUNT(*) as completed
            FROM user_type_2_evaluation_dataset
            WHERE (
                (assigned_user_id_1 = %s AND user_id_1_score IS NOT NULL) OR
                (assigned_user_id_2 = %s AND user_id_2_score IS NOT NULL) OR
                (assigned_user_id_3 = %s AND user_id_3_score IS NOT NULL) OR
                (assigned_user_id_4 = %s AND user_id_4_score IS NOT NULL)
            )
            AND status = 'active'
        """
            , (user_id, user_id, user_id, user_id))
        completed_result = cursor.fetchone()
        completed = completed_result['completed'] if completed_result else 0
        cursor.execute('SELECT user_status FROM test_user WHERE id = %s', (
            user_id,))
        user_result = cursor.fetchone()
        user_status = user_result['user_status'] if user_result else 'unknown'
        cursor.close()
        conn.close()
        all_completed = completed >= total and total > 0
        response_data = {'success': True, 'total': total, 'completed':
            completed, 'remaining': total - completed, 'all_completed':
            all_completed, 'user_status': user_status}
        if all_completed:
            response_data['completion_code'] = None
        return jsonify(response_data)
    except Exception as e:
        logger.error(f'Error getting status: {str(e)}')
        return jsonify({'success': False, 'error': str(e)}), 500
