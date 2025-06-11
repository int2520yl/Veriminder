from flask import Flask, request
import hello
import user_testing
import interface
import analyst_interface
import logging
from logging.handlers import RotatingFileHandler
import os
from services.nl_to_sql_service import bp as nl_to_sql_bp
from services.suggestions_service import bp as suggestions_bp
from services.analysis_service import bp as analysis_bp
from services.user_feedback_service import bp as user_feedback_bp
from services.analyst_feedback_service import bp as analyst_feedback_bp
from services.streaming_service import bp as streaming_bp


def create_app():
    app = Flask(__name__)
    app.secret_key = 'YOUR_FLASK_SECRET_KEY'
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
    app.config['PROPAGATE_EXCEPTIONS'] = True
    app.config['APPLICATION_ROOT'] = '/'
    app.register_blueprint(hello.bp)
    app.register_blueprint(user_testing.bp)
    app.register_blueprint(interface.bp)
    app.register_blueprint(analyst_interface.bp)
    app.register_blueprint(nl_to_sql_bp)
    app.register_blueprint(suggestions_bp)
    app.register_blueprint(analysis_bp)
    app.register_blueprint(user_feedback_bp)
    app.register_blueprint(analyst_feedback_bp)
    app.register_blueprint(streaming_bp)
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    access_logger = logging.getLogger('werkzeug')
    access_handler = RotatingFileHandler(os.path.join(log_dir,
        'flask_access.log'), maxBytes=1024 * 1024 * 10, backupCount=5)
    access_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s [in %(pathname)s:%(lineno)d]'
        )
    access_handler.setFormatter(access_formatter)
    access_logger.addHandler(access_handler)
    access_logger.setLevel(logging.ERROR)
    error_logger = logging.getLogger('my_app')
    error_handler = RotatingFileHandler(os.path.join(log_dir,
        'flask_error.log'), maxBytes=1024 * 1024 * 10, backupCount=5)
    error_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s [in %(pathname)s:%(lineno)d]'
        )
    error_handler.setFormatter(error_formatter)
    error_logger.addHandler(error_handler)
    access_logger.setLevel(logging.ERROR)

    @app.before_request
    def log_request_info():
        error_logger.info(
            f'Request: {request.method} {request.url} from {request.remote_addr}'
            )

    @app.errorhandler(500)
    def internal_error(error):
        error_logger.exception(f'500 error: {error}')
        return 'Internal Server Error', 500

    @app.after_request
    def add_header(response):
        if 'Cache-Control' not in response.headers:
            response.headers['Cache-Control'] = (
                'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
                )
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '-1'
        return response
    from services import stream_manager
    stream_manager.start_cleanup_scheduler()
    return app


app = create_app()
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80, debug=False, threaded=True)
