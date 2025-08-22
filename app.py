from flask import Flask, render_template, redirect, url_for, flash, request, session
from forms import LoginForm
import logging

app = Flask(__name__)
app.config['SECRET_KEY'] = '1a2b3c4d5e6f7g8h9i0j'
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SESSION_PERMANENT'] = True

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data
        password = form.password.data

        # Hardcoded accounts
        teacher_email = "teacher@insighteval.com"
        student_email = "student@insighteval.com"
        dummy_password = "111111"  # For testing

        if email == teacher_email and password == dummy_password:
            return redirect(url_for('teacher_dashboard'))
        elif email == student_email and password == dummy_password:
            return redirect(url_for('student_dashboard'))
        else:
            flash("Invalid email or password", "error")

    return render_template('login.html', form=form)


@app.route('/teacher/dashboard')
def teacher_dashboard():
    return render_template('teacher_dashboard.html')


@app.route('/student/dashboard')
def student_dashboard():
    return render_template('student_dashboard.html')

@app.route('/dashboard')
def dashboard():
    if 'logged_in' not in session or not session['logged_in']:
        logger.info("Unauthorized dashboard access, redirecting to login")
        flash('Please log in to access the dashboard.', 'error')
        return redirect(url_for('login'))
    return render_template('dashboard.html')

@app.route('/logout')
def logout():
    session.clear()
    logger.info("Session cleared via logout")
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)