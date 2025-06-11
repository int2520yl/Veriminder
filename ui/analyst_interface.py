from flask import Blueprint, render_template, request, session, redirect, url_for, flash
import mysql.connector
import logging
import os
bp = Blueprint('analyst_interface', __name__)
ENVIRONMENT = 'local'
DB_CONFIG = {
    'host': 'YOUR_DATABASE_HOST',
    'port': 'YOUR_DATABASE_POST',
    'user': 'YOUR_DATABASE_USER',
    'password': 'YOUR_DATABASE_PASSWORD',
    'database': 'YOUR_DATABASE_NAME'
}

os.makedirs('logs', exist_ok=True)
logging.basicConfig(filename='logs/analyst_interface.log', level=logging.
    INFO, format=
    '%(asctime)s - %(levelname)s - %(pathname)s:%(lineno)d - %(message)s')
logger = logging.getLogger(__name__)


def get_db_connection():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except mysql.connector.Error as e:
        logger.error(f'Database connection error: {str(e)}')
        raise


@bp.route('/analyst', methods=['GET', 'POST'])
def index():
    error_message = None
    if request.method == 'GET':
        session.clear()
        logger.info('Session cleared for new analyst visit')
    if request.method == 'POST':
        prolific_id = request.form.get('prolific_id', '').strip()
        if not prolific_id:
            error_message = 'Please enter your Prolific ID.'
        elif len(prolific_id) > 200:
            error_message = 'Prolific ID must be less than 200 characters.'
        if not error_message:
            conn = None
            try:
                conn = get_db_connection()
                cursor = conn.cursor(dictionary=True)
                cursor.execute(
                    'SELECT id, user_status FROM test_user WHERE prolific_user_id = %s'
                    , (prolific_id,))
                existing_user = cursor.fetchone()
                if existing_user:
                    if existing_user['user_status'] == 'completed':
                        error_message = (
                            'You have already completed all assigned evaluations.'
                            )
                    else:
                        user_id = existing_user['id']
                        session['user_id'] = user_id
                        session['user_type'] = 'type_2'
                        logger.info(
                            f'Existing user with ID {user_id} logged in')
                        return redirect(url_for(
                            'analyst_feedback_service.dashboard'))
                else:
                    cursor.execute(
                        'INSERT INTO test_user (prolific_user_id, test_user_type, user_status) VALUES (%s, %s, %s)'
                        , (prolific_id, 'type_2', 'active'))
                    user_id = cursor.lastrowid
                    conn.commit()
                    assigned_count = assign_datasets_to_user(user_id)
                    if assigned_count == 0:
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute('DELETE FROM test_user WHERE id = %s',
                            (user_id,))
                        conn.commit()
                        cursor.close()
                        conn.close()
                        error_message = (
                            'No evaluation datasets are currently available. Please try again later.'
                            )
                    else:
                        session['user_id'] = user_id
                        session['user_type'] = 'type_2'
                        logger.info(
                            f'New user created with ID {user_id}, assigned to {assigned_count} datasets'
                            )
                        flash(
                            f'You have been assigned {assigned_count} decisions to evaluate.'
                            , 'success')
                        return redirect(url_for(
                            'analyst_feedback_service.dashboard'))
                cursor.close()
            except Exception as e:
                logger.error(f'Error processing analyst registration: {str(e)}'
                    )
                if conn and conn.in_transaction:
                    conn.rollback()
                error_message = (
                    'An error occurred while processing your request. Please try again.'
                    )
            finally:
                if conn:
                    conn.close()
    return render_template('analyst_interface.html', error_message=
        error_message)


def assign_datasets_to_user(user_id, max_assignments=5):
    assigned_count = 0
    conn = None
    if ENVIRONMENT == 'server':
        available_slots = [1, 2]
        slot_condition = (
            'assigned_user_id_1 IS NULL OR assigned_user_id_2 IS NULL')
        slot_selection = 'assigned_user_id_1, assigned_user_id_2'
    else:
        available_slots = [3, 4]
        slot_condition = (
            'assigned_user_id_3 IS NULL OR assigned_user_id_4 IS NULL')
        slot_selection = 'assigned_user_id_3, assigned_user_id_4'
    logger.info(f'Using environment: {ENVIRONMENT}, slots: {available_slots}')
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = f"""
            SELECT id, dataset_id 
            FROM user_type_2_evaluation_dataset 
            WHERE status = 'active' 
            AND ({slot_condition})
            LIMIT %s
            FOR UPDATE
        """
        cursor.execute(query, (max_assignments,))
        available_datasets = cursor.fetchall()
        for dataset in available_datasets:
            query = f"""
                SELECT {slot_selection}
                FROM user_type_2_evaluation_dataset 
                WHERE id = %s
                FOR UPDATE
            """
            cursor.execute(query, (dataset['id'],))
            assignment_slots = cursor.fetchone()
            slot_to_update = None
            for i in available_slots:
                slot_name = f'assigned_user_id_{i}'
                if slot_name in assignment_slots and assignment_slots[slot_name
                    ] is None:
                    slot_to_update = slot_name
                    break
            if slot_to_update:
                update_query = (
                    f'UPDATE user_type_2_evaluation_dataset SET {slot_to_update} = %s WHERE id = %s'
                    )
                cursor.execute(update_query, (user_id, dataset['id']))
                assigned_count += 1
                logger.info(
                    f"Assigned user {user_id} to dataset {dataset['dataset_id']} in slot {slot_to_update}"
                    )
        conn.commit()
        cursor.close()
        return assigned_count
    except Exception as e:
        logger.error(f'Error assigning datasets to user {user_id}: {str(e)}')
        if conn and conn.in_transaction:
            conn.rollback()
        return 0
    finally:
        if conn:
            conn.close()
