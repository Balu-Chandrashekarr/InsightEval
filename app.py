from flask import Flask, render_template, redirect, url_for, flash, request, session
from forms import LoginForm, RegisterForm, ProfileForm
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = '1a2b3c4d5e6f7g8h9i0j'
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['UPLOAD_FOLDER'] = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def home():
    if 'profile_submitted' in session and session['profile_submitted']:
        return redirect(url_for('verification'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'profile_submitted' in session and session['profile_submitted']:
        return redirect(url_for('verification'))
    form = LoginForm()
    if form.validate_on_submit():
        flash(f'Welcome, {form.email.data}!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('login.html', form=form)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'profile_submitted' in session and session['profile_submitted']:
        return redirect(url_for('verification'))
    form = RegisterForm()
    if form.validate_on_submit():
        session['institution'] = form.institution.data
        flash(f'Registration successful for {form.institution.data}!', 'success')
        return redirect(url_for('profile_setup'))
    return render_template('register.html', form=form)

@app.route('/profile-setup', methods=['GET', 'POST'])
def profile_setup():
    if 'profile_submitted' in session and session['profile_submitted']:
        return redirect(url_for('verification'))
    form = ProfileForm()
    if form.validate_on_submit():
        name = form.name.data
        bio = form.bio.data
        file = form.profile_pic.data
        profile_pic_path = None
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            profile_pic_path = f'uploads/{filename}'
        
        # Store profile data in session (replace with database later)
        session['name'] = name
        session['bio'] = bio
        session['profile_pic'] = profile_pic_path or 'images/default_profile.jpg'
        session['profile_submitted'] = True
        flash('Profile submitted for verification!', 'success')
        return redirect(url_for('verification'))
    
    return render_template('profile_setup.html', form=form)

@app.route('/verification')
def verification():
    if 'profile_submitted' not in session or not session['profile_submitted']:
        return redirect(url_for('home'))
    return render_template('verification.html')

@app.route('/dashboard')
def dashboard():
    if 'profile_submitted' in session and session['profile_submitted']:
        return redirect(url_for('verification'))
    return render_template('dashboard.html')

if __name__ == '__main__':
    app.run(debug=True)