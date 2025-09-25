from flask import Flask, render_template, redirect, url_for, flash, request, session
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, Length
import logging

app = Flask(__name__)
app.config['SECRET_KEY'] = '1a2b3c4d5e6f7g8h9i0j'
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# =============================================================================
#  Forms
# =============================================================================
class LoginForm(FlaskForm):
    """Form for user login."""
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    submit = SubmitField('Login')

# =============================================================================
#  Routes
# =============================================================================

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    
    if form.validate_on_submit():
        # Using dummy credentials for testing without a database
        if form.email.data == 'student@insighteval.com' and form.password.data == '111111':
            session['user_role'] = 'student'
            session['user_name'] = 'Adarsht'
            session['user_email'] = form.email.data # Added for profile page
            return redirect(url_for('dashboard'))
            
        elif form.email.data == 'teacher@insighteval.com' and form.password.data == '111111':
            session['user_role'] = 'teacher'
            session['user_name'] = 'Ms. Anandhi'
            session['user_email'] = form.email.data # Added for profile page
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid email or password", "error")

    return render_template('login.html', form=form)


@app.route('/dashboard')
def dashboard():
    """ Renders the main dashboard for any logged-in user. """
    # Protect the route: ensure a user is logged in
    if 'user_role' not in session:
        flash('You must be logged in to view the dashboard.', 'error')
        return redirect(url_for('login'))
    
    # Renders the new unified dashboard
    return render_template('dashboard.html')

# ========== NEW ROUTE FOR THE CLASSROOM PAGE ==========
@app.route('/classroom/<int:classroom_id>')
def classroom(classroom_id):
    """ Renders the view for a specific classroom. """
    if 'user_role' not in session:
        flash('You must be logged in to view a classroom.', 'error')
        return redirect(url_for('login'))
    
    # The classroom_id can be used later to fetch data for that specific class.
    # For now, we just render the template you provided.
    return render_template('classroom.html', classroom_id=classroom_id)


@app.route('/profile')
def profile():
    """ Renders the user profile page. """
    if 'user_role' not in session:
        flash('You must be logged in to view your profile.', 'error')
        return redirect(url_for('login'))
        
    return render_template('profile.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)

