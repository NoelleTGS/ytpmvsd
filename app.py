import datetime
import os
import time

import dotenv
import ffmpeg
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_migrate import Migrate
from flask_moment import Moment
from sqlalchemy import func
from werkzeug.utils import secure_filename

import database_functions
from models import db, Sample, User, likes_table

dotenv.load_dotenv()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY')
app.config['MAX_CONTENT_LENGTH'] = 10 * 1000 * 1000

db.init_app(app)
migrate = Migrate(app, db)
moment = Moment(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'  # Redirect users to 'login' page if not authenticated


def create_thumbnail(video_path, thumbnail_path):
    try:
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        (
            ffmpeg
            .input(video_path, ss=0)
            .filter('scale', -1, 480)
            .output(thumbnail_path, vframes=1)
            .run(capture_stdout=True, capture_stderr=True)
        )

        print(f"Thumbnail saved at {thumbnail_path}")

    except Exception as e:
        print(f"An error occurred: {e}")


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_name = request.form['login'].lower()
        password = request.form['password']

        user = User.query.filter(func.lower(User.email) == login_name).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('home_page'))

        user = User.query.filter(func.lower(User.username) == login_name).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('home_page'))
        flash("Login or password incorrect.", "error")
        return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home_page'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        if User.query.filter(User.username.ilike(username)).first():
            flash("Username is already in use.", "error")
            return redirect(url_for('register'))

        if User.query.filter(User.email.ilike(email)).first():
            flash("Email is already in use.", "error")
            return redirect(url_for('register'))

        user = User(username=username, email=email)
        user.set_password(password)

        db.session.add(user)
        db.session.commit()
        flash("Successfully registered.", "success")
        return redirect(url_for('login'))

    return render_template('register.html')


@app.context_processor
def inject_user():
    return {'current_user': current_user}


@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html', title='YTPMV Sample Database')

@app.errorhandler(413)
def request_entity_too_large(error):
    flash("File too large. Max supported filesize is 10MB.", "error")
    return redirect(url_for('upload'))



@app.route('/')
def home_page():
    recent_samples = Sample.query.order_by(Sample.upload_date.desc()).limit(8).all()
    top_samples = (
        db.session.query(Sample)
        .outerjoin(likes_table, Sample.id == likes_table.c.sample_id)
        .group_by(Sample.id)
        .order_by(func.count(likes_table.c.user_id).desc())
        .limit(8)
        .all()
    )
    return render_template('home.html', title='YTPMV Sample Database', top_samples=top_samples,
                           recent_samples=recent_samples, date=datetime.datetime.now(datetime.UTC))


@app.route('/samples')
def all_samples():
    samples = Sample.query.all()
    return render_template('samples.html', title='YTPMV Sample Database', samples=samples,
                           date=datetime.datetime.now(datetime.UTC))


ALLOWED_UPLOAD_EXTENSIONS = {'mp4'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_UPLOAD_EXTENSIONS


def check_video(upload_path):
    try:
        ffmpeg.probe(upload_path)
        return True
    except ffmpeg.Error:
        return False


@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        if 'file' not in request.files:
            return redirect(request.url)

        file = request.files['file']

        if file.filename == '':
            return redirect(request.url)

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            upload_path = os.path.join('static/media/samps', filename)
            file.save(upload_path)

            if not check_video(upload_path):
                flash("There is an error in the file. Please make sure it is a valid .mp4 file.", "error")
                os.remove(upload_path)
                return redirect(url_for('upload'))

            current_time = int(time.time() * 100)
            create_thumbnail(upload_path, f"static/media/thumbs/{current_time}.png")

            database_functions.add_sample_to_db(filename, datetime.datetime.now(datetime.UTC),
                                                str(current_time) + '.png', current_user.id)
            return redirect(url_for('home_page'))

    return render_template('upload.html', title='YTPMV Sample Database')

def get_metadata(sample_id):
    sample = Sample.query.get_or_404(sample_id)
    file = os.path.join('static/media/samps', sample.filename)

    probe = ffmpeg.probe(file)

    return probe


@app.route('/sample/<int:sample_id>')
def sample_page(sample_id):
    sample = Sample.query.get_or_404(sample_id)
    uploader = User.query.get_or_404(sample.uploader)

    return render_template('sample.html', title=f"{sample.filename}", sample=sample, uploader=uploader)


@app.route('/sample/like/<int:sample_id>', methods=['POST'])
@login_required
def like_sample(sample_id):
    sample = Sample.query.get_or_404(sample_id)

    if current_user in sample.likes:
        sample.likes.remove(current_user)
        liked = False
    else:
        sample.likes.append(current_user)
        liked = True

    db.session.commit()
    return jsonify(success=True, likes=len(sample.likes), liked=liked)


@app.route('/sample/delete/<int:sample_id>', methods=['POST'])
@login_required
def delete_sample(sample_id):
    if not current_user.is_admin:
        return jsonify({"message": "Access denied"}), 403

    sample = Sample.query.get(sample_id)
    if sample:
        os.remove(os.path.join('static/media/thumbs', sample.thumbnail_filename))
        os.remove(os.path.join('static/media/samps', sample.filename))
        db.session.delete(sample)
        db.session.commit()
        return jsonify({"message": "Sample deleted successfully."})
    return jsonify({"message": "There was an error deleting the sample."})


if __name__ == '__main__':
    app.run(debug=True, host='192.168.7.2', port=5000)
