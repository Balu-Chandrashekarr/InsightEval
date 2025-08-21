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
        session['email'] = form.email.data
        session['logged_in'] = True
        logger.info(f"User {form.email.data} logged in")
        flash(f'Welcome, {form.email.data}!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('login.html', form=form)

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