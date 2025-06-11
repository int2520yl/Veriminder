import mysql.connector
import json
import logging
import os
import time
from datetime import datetime
BATCH_SIZE = 10
TEST_MODE = False
DB_CONFIG = {
    'host': 'YOUR_DATABASE_HOST',
    'port': 'YOUR_DATABASE_POST',
    'user': 'YOUR_DATABASE_USER',
    'password': 'YOUR_DATABASE_PASSWORD',
    'database': 'YOUR_DATABASE_NAME'
}

os.makedirs('logs', exist_ok=True)
logging.basicConfig(level=logging.INFO, format=
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s', handlers=[
    logging.FileHandler(os.path.join('logs',
    f"question_to_sql_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")),
    logging.StreamHandler()])
logger = logging.getLogger(__name__)


def connect_to_db():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        logger.info('Successfully connected to the database')
        return conn
    except Exception as e:
        logger.error(f'Failed to connect to the database: {str(e)}')
        raise


def check_for_processing_records(conn):
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT COUNT(*) as count FROM dataset WHERE question_to_sql_status = 'processing'"
        )
    result = cursor.fetchone()
    cursor.close()
    if result['count'] > 0:
        logger.error(
            f"Found {result['count']} records still in 'processing' state. Exiting."
            )
        return False
    return True


def get_datasets_for_processing(conn, batch_size):
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, question FROM dataset WHERE status = 'active' AND question_to_sql_status = 'ready' LIMIT %s"
        , (batch_size,))
    datasets = cursor.fetchall()
    if datasets:
        dataset_ids = [d['id'] for d in datasets]
        placeholders = ', '.join(['%s'] * len(dataset_ids))
        update_query = f"""
        UPDATE dataset 
        SET question_to_sql_status = 'processing'
        WHERE id IN ({placeholders})
        """
        cursor.execute(update_query, dataset_ids)
        conn.commit()
        logger.info(
            f'Marked {len(datasets)} datasets for processing: {dataset_ids}')
    cursor.close()
    return datasets


def insert_queries(conn, datasets):
    cursor = conn.cursor()
    success_count = 0
    failure_count = 0
    for dataset in datasets:
        try:
            dataset_id = dataset['id']
            question_data = json.loads(dataset['question']) if isinstance(
                dataset['question'], str) else dataset['question']
            question_text = question_data.get('text', '')
            if not question_text:
                logger.warning(
                    f'Empty question text for dataset ID {dataset_id}')
            insert_query = """
            INSERT INTO query 
            (dataset_id, query_model, NL_question, model_query_sequence_index, 
             sql_generation_status, execution_status, status, version)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(insert_query, (dataset_id, 'question_to_sql',
                question_text, 1, 'pending', 'pending', 'active', 1))
            update_query = """
            UPDATE dataset
            SET question_to_sql_status = 'success'
            WHERE id = %s
            """
            cursor.execute(update_query, (dataset_id,))
            success_count += 1
        except Exception as e:
            logger.error(
                f"Error processing dataset ID {dataset['id']}: {str(e)}")
            try:
                failure_update_query = """
                UPDATE dataset
                SET question_to_sql_status = 'failed'
                WHERE id = %s
                """
                cursor.execute(failure_update_query, (dataset['id'],))
                failure_count += 1
            except Exception as inner_e:
                logger.error(
                    f"Failed to update status for dataset ID {dataset['id']}: {str(inner_e)}"
                    )
    conn.commit()
    cursor.close()
    logger.info(
        f'Processed {success_count} datasets successfully and {failure_count} failed'
        )
    return success_count, failure_count


def process_batch(conn, batch_size):
    datasets = get_datasets_for_processing(conn, batch_size)
    if not datasets:
        logger.info('No datasets found for processing')
        return 0
    success_count, _ = insert_queries(conn, datasets)
    return len(datasets)


def main():
    start_time = time.time()
    total_processed = 0
    logger.info('Starting question_to_sql process')
    try:
        conn = connect_to_db()
        if not check_for_processing_records(conn):
            conn.close()
            return
        batch_count = 0
        while True:
            batch_count += 1
            batch_start_time = time.time()
            logger.info(f'Processing batch {batch_count}')
            batch_size = 1 if TEST_MODE else BATCH_SIZE
            processed_count = process_batch(conn, batch_size)
            if processed_count == 0:
                logger.info('No more datasets to process')
                break
            total_processed += processed_count
            batch_elapsed_time = time.time() - batch_start_time
            logger.info(
                f'Batch {batch_count} completed in {batch_elapsed_time:.2f} seconds'
                )
            if TEST_MODE:
                logger.info('Test mode enabled - stopping after one batch')
                break
        conn.close()
        elapsed_time = time.time() - start_time
        logger.info(
            f'Processing completed successfully in {elapsed_time:.2f} seconds')
        logger.info(f'Total datasets processed: {total_processed}')
    except Exception as e:
        logger.error(f'Error in main process: {str(e)}')


if __name__ == '__main__':
    main()
