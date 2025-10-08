from os import abort
from flask import Flask, render_template, redirect, url_for, flash, session, request
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, Length
import logging
from datetime import datetime
from jinja2.exceptions import TemplateNotFound

app = Flask(__name__)
app.config['SECRET_KEY'] = '1a2b3c4d5e6f7g8h9i0j'
app.config['TEMPLATES_AUTO_RELOAD'] = True

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
    """Redirects the root URL to the login page."""
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    Handles user login. This route will now always display the login page,
    only redirecting to the dashboard upon a successful form submission.
    """
    form = LoginForm()
        
    if form.validate_on_submit():
        if form.email.data == 'student@insighteval.com' and form.password.data == '111111':
            session['user_role'] = 'student'
            session['user_name'] = 'Adarsht'
            session['user_email'] = form.email.data
            flash(f"Welcome back, {session['user_name']}!", "success")
            return redirect(url_for('dashboard'))
            
        elif form.email.data == 'teacher@insighteval.com' and form.password.data == '111111':
            session['user_role'] = 'teacher'
            session['user_name'] = 'Ms. Anandhi'
            session['user_email'] = form.email.data
            flash(f"Welcome back, {session['user_name']}!", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid email or password", "error")

    # The login template is always rendered if the request is GET or form validation fails
    return render_template('login.html', form=form)


@app.route('/dashboard')
def dashboard():
    """Renders the main dashboard for any logged-in user."""
    if 'user_role' not in session:
        flash('You must be logged in to view the dashboard.', 'error')
        return redirect(url_for('login'))
    
    return render_template('dashboard.html')


@app.route('/classroom/<int:classroom_id>')
def classroom(classroom_id):
    """Renders the specific classroom page."""
    if 'user_role' not in session:
        return redirect(url_for('login'))
        
    posts = session.get('posts', [])
    return render_template('classroom.html', classroom_id=classroom_id, posts=posts)
    

@app.route('/create_test', methods=['GET', 'POST'])
def create_test():
    """Renders the page for creating a new test and handles submission."""
    if 'user_role' not in session:
        flash('You must be logged in to create a test.', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        test_title = request.form.get('test-title')
        test_description = request.form.get('test-description')

        if 'posts' not in session:
            session['posts'] = []

        new_test_post = {
            'type': 'test',
            'title': test_title,
            'content': test_description,
            'author': session.get('user_name', 'Teacher'),
            'date': datetime.now().strftime('%b %d, %Y')
        }

        session['posts'].insert(0, new_test_post)
        session.modified = True 

        flash('Test has been published successfully!', 'success')
        # Redirect to a default classroom (ID 1) for demonstration
        return redirect(url_for('classroom', classroom_id=1))
        
    return render_template('create_test.html')

# ========== NEW DYNAMIC ROUTE FOR COURSES ==========
@app.route('/course/<string:course_name>')
def course(course_name):
    """ Renders a specific course page based on the name. """
    if 'user_role' not in session:
        flash('You must be logged in to view courses.', 'error')
        return redirect(url_for('login'))
    
    try:
        # Dynamically create the template path, e.g., "courses/dsa.html"
        template_path = f"courses/{course_name}.html"
        return render_template(template_path)
    except TemplateNotFound:
        # If the HTML file doesn't exist, show a 404 error
        abort(404)


@app.route('/logout')
def logout():
    """Clears the user session."""
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)

