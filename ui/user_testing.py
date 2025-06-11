from flask import Blueprint, render_template, request, session, redirect, url_for, flash
import mysql.connector
import logging
import os
from services import stream_manager
bp = Blueprint('user_testing', __name__)
DB_CONFIG = {
    'host': 'YOUR_DATABASE_HOST',
    'port': 'YOUR_DATABASE_POST',
    'user': 'YOUR_DATABASE_USER',
    'password': 'YOUR_DATABASE_PASSWORD',
    'database': 'YOUR_DATABASE_NAME'
}

os.makedirs('logs', exist_ok=True)
logging.basicConfig(filename='logs/user_testing.log', level=logging.INFO,
    format=
    '%(asctime)s - %(levelname)s - %(pathname)s:%(lineno)d - %(message)s')
logger = logging.getLogger(__name__)


def get_db_connection():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except mysql.connector.Error as e:
        logger.error(f'Database connection error: {str(e)}')
        raise


@bp.route('/user_testing', methods=['GET', 'POST'])
def index():
    error_message = None
    if request.method == 'GET':
        session.clear()
        logger.info('Session cleared for new user testing visit')
    if request.method == 'POST':
        prolific_id = request.form.get('prolific_id', '').strip()
        if not error_message:
            conn = None
            try:
                conn = get_db_connection()
                cursor = conn.cursor(dictionary=True)
                cursor.execute(
                    'SELECT id FROM test_user WHERE prolific_user_id = %s',
                    (prolific_id,))
                existing_user = cursor.fetchone()
                if existing_user:
                    error_message = (
                        'This Prolific ID is already registered in our system.'
                        )
                else:
                    cursor.execute(
                        "SELECT d.id FROM dataset d, bird_question_linked_to_cluster c WHERE d.source=c.id AND d.status='slowzed' AND c.cluster_id IN (4, 17)"
                        )
                    eligible_dataset_ids = [row['id'] for row in cursor.
                        fetchall()]
                    logger.info(
                        f'Found {len(eligible_dataset_ids)} eligible datasets from targeted clusters'
                        )
                    if not eligible_dataset_ids:
                        conn.rollback()
                        error_message = (
                            'No datasets available from the required study groups.'
                            )
                    else:
                        placeholders = ', '.join(['%s'] * len(
                            eligible_dataset_ids))
                        query = (
                            f"SELECT id, test_user_id_1, test_user_id_2 FROM dataset WHERE id IN ({placeholders}) AND status IN ('slowzed', 'active') AND baqr_status = 'slowzed' AND (test_user_id_1 IS NULL OR test_user_id_2 IS NULL) LIMIT 1 FOR UPDATE"
                            )
                        cursor.execute(query, eligible_dataset_ids)
                        available_dataset = cursor.fetchone()
                        if not available_dataset:
                            conn.rollback()
                            error_message = (
                                'No current seats available for study participants.'
                                )
                        else:
                            dataset_id = available_dataset['id']
                            cursor.execute(
                                'INSERT INTO test_user (prolific_user_id, user_status) VALUES (%s, %s)'
                                , (prolific_id, 'active'))
                            user_id = cursor.lastrowid
                            if available_dataset['test_user_id_1'] is None:
                                cursor.execute(
                                    'UPDATE dataset SET test_user_id_1 = %s WHERE id = %s'
                                    , (user_id, dataset_id))
                            else:
                                cursor.execute(
                                    'UPDATE dataset SET test_user_id_2 = %s WHERE id = %s'
                                    , (user_id, dataset_id))
                            conn.commit()
                            session['user_id'] = user_id
                            stream_manager.clear_user_streams(user_id)
                            logger.info(
                                f'User with Prolific ID {prolific_id} successfully registered. Assigned to dataset ID {dataset_id}.'
                                )
                            logger.info(
                                f'User with Prolific ID {prolific_id} successfully registered. Assigned to dataset ID {dataset_id}.'
                                )
                            flash(
                                'Successfully registered. Starting user testing session.'
                                , 'success')
                            return redirect(url_for('interface.index',
                                dataset_id=dataset_id))
                if conn.in_transaction:
                    conn.rollback()
                cursor.close()
            except Exception as e:
                logger.error(f'Error processing Prolific ID: {str(e)}')
                if conn and conn.in_transaction:
                    conn.rollback()
                error_message = (
                    'An error occurred while processing your request. Please try again.'
                    )
            finally:
                if conn:
                    conn.close()
    return render_template('user_testing.html', error_message=error_message)
