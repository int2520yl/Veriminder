from flask import Blueprint, render_template, session
from flask import current_app
bp = Blueprint('hello', __name__)


@bp.route('/', methods=['GET', 'POST'])
def index():
    session.clear()
    return render_template('hello.html')
