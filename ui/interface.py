from flask import Blueprint, render_template, request, session, redirect, url_for, flash
import mysql.connector
import json
import logging
import os
import random
import string
bp = Blueprint('interface', __name__)
DB_CONFIG = {
    'host': 'YOUR_DATABASE_HOST',
    'port': 'YOUR_DATABASE_POST',
    'user': 'YOUR_DATABASE_USER',
    'password': 'YOUR_DATABASE_PASSWORD',
    'database': 'YOUR_DATABASE_NAME'
}

os.makedirs('logs', exist_ok=True)
logging.basicConfig(filename='logs/interface.log', level=logging.INFO,
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


def create_auto_user():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        random_suffix = random.randint(0, 50)
        cursor.execute('SELECT MAX(id) as max_id FROM test_user')
        result = cursor.fetchone()
        next_id = 1 if not result or not result['max_id'] else result['max_id'
            ] + 1
        prolific_id = f'auto_{next_id}_{random_suffix}'
        cursor.execute(
            'INSERT INTO test_user (prolific_user_id, test_user_type, user_status) VALUES (%s, %s, %s)'
            , (prolific_id, 'type_1', 'active'))
        user_id = cursor.lastrowid
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(
            f'Created auto user with prolific_id={prolific_id}, user_id={user_id}'
            )
        return user_id
    except Exception as e:
        logger.error(f'Error creating auto user: {str(e)}')
        if conn and conn.in_transaction:
            conn.rollback()
        if conn:
            conn.close()
        return None


@bp.route('/interface', methods=['GET', 'POST'])
def index():
    auto_user = request.args.get('auto_user') == '1'
    user_id = session.get('user_id')
    user_type = session.get('user_type', 'type_1')
    if auto_user and not user_id:
        user_id = create_auto_user()
        if user_id:
            session['user_id'] = user_id
            session['user_type'] = 'type_1'
            user_type = 'type_1'
            logger.info(f'Auto user created, user_id={user_id}')
        else:
            logger.error('Failed to create auto user')
            flash(
                'Failed to create automatic user. Please try again or register manually.'
                , 'danger')
            return redirect(url_for('user_testing.index'))
    if not user_id:
        user_id = request.args.get('user_id')
        if user_id:
            try:
                user_id = int(user_id)
                session['user_id'] = user_id
                logger.info(f'Set user_id={user_id} from GET parameter')
            except ValueError:
                logger.error(f'Invalid user_id parameter: {user_id}')
                flash('Invalid user ID parameter.', 'danger')
                return redirect(url_for('hello.index'))
    if not user_id:
        logger.warning('No user_id available, redirecting to user_testing')
        return redirect(url_for('user_testing.index'))
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT id, test_user_type FROM test_user WHERE id = %s'
            , (user_id,))
        user_exists = cursor.fetchone()
        cursor.close()
        if not user_exists:
            logger.warning(
                f'User ID {user_id} not found in test_user table, redirecting to user_testing'
                )
            flash('User ID not found. Please register first.', 'warning')
            return redirect(url_for('user_testing.index'))
        user_type = user_exists['test_user_type']
        session['user_type'] = user_type
        if user_type == 'type_2':
            logger.info(
                f'User {user_id} is type_2, redirecting to analyst interface')
            return redirect(url_for('analyst_interface.dashboard'))
    except Exception as e:
        logger.error(f'Error validating user_id: {str(e)}')
        flash('An error occurred while validating your user ID.', 'danger')
        return redirect(url_for('hello.index'))
    if request.args.get('start_new') == '1':
        dataset_id = None
        user_id = session.get('user_id')
        if user_id:
            from services import stream_manager
            stream_manager.clear_user_streams(user_id)
        logger.info('New dataset requested, cleared dataset_id and streams')
    else:
        dataset_id = request.args.get('dataset_id')
        if dataset_id:
            try:
                dataset_id = int(dataset_id)
                logger.info(f'Set dataset_id={dataset_id} from GET parameter')
            except ValueError:
                logger.error(f'Invalid dataset_id parameter: {dataset_id}')
                dataset_id = None
    question_text = ''
    decision_text = ''
    form_readonly = False
    if dataset_id:
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT * FROM dataset WHERE id = %s AND status in ('slowzed', 'active')"
                , (dataset_id,))
            record = cursor.fetchone()
            cursor.close()
            conn.close()
            if record:
                question_json = record.get('question')
                decision_json = record.get('decision')
                if question_json:
                    try:
                        question_data = json.loads(question_json)
                        question_text = question_data.get('text', '')
                    except (json.JSONDecodeError, TypeError):
                        logger.error(
                            f'Invalid question JSON for dataset_id={dataset_id}'
                            )
                if decision_json:
                    try:
                        decision_data = json.loads(decision_json)
                        decision_text = decision_data.get('text', '')
                    except (json.JSONDecodeError, TypeError):
                        logger.error(
                            f'Invalid decision JSON for dataset_id={dataset_id}'
                            )
                form_readonly = bool(question_text) or bool(decision_text)
                logger.info(
                    f'Dataset record found. form_readonly={form_readonly}')
            else:
                logger.warning(
                    f'No dataset record found for dataset_id={dataset_id}')
                dataset_id = None
                session.pop('dataset_id', None)
        except Exception as e:
            logger.error(f'Error fetching dataset record: {str(e)}')
            dataset_id = None
            session.pop('dataset_id', None)
    logger.info(
        f'Rendering interface for dataset_id={dataset_id}, user_id={user_id}, user_type={user_type}'
        )
    return render_template('interface.html', dataset_id=dataset_id or '',
        user_id=user_id or '', question_text=question_text, decision_text=
        decision_text, form_readonly=form_readonly, user_type=user_type)
