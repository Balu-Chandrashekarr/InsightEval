from flask import Flask, jsonify, render_template, redirect, url_for, flash, session, request, abort, send_from_directory
from flask_wtf import FlaskForm
import pyrebase
import firebase_admin
from firebase_admin import credentials, firestore , db
from wtforms import StringField, PasswordField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, Length,Optional
import logging
from datetime import datetime
from jinja2.exceptions import TemplateNotFound



app = Flask(__name__)

# =============================================================================
#  Firebase Configuration
config = {
    'apiKey': "AIzaSyCnx9tSj5_bJk4qwdoHutv_73iUoGHINWE",
    'authDomain': "insighteval-e56af.firebaseapp.com",
    'projectId': "insighteval-e56af",
    'storageBucket': "insighteval-e56af.appspot.com",
    'messagingSenderId': "184739995469",
    'appId': "1:184739995469:web:9390b124eced0431ff6104",
    'measurementId': "G-S6KDMGXBP8",
    # ✅ Correct Realtime Database URL (replace this with yours from Firebase console)
    'databaseURL': "https://insighteval-e56af-default-rtdb.firebaseio.com/"
}

# ✅ Initialize Pyrebase (client SDK)
firebase = pyrebase.initialize_app(config)
auth = firebase.auth()

# ✅ Initialize Firebase Admin SDK (server SDK)
if not firebase_admin._apps:
    cred = credentials.Certificate("insighteval-e56af-firebase-adminsdk-fbsvc-3c042c68fa.json")
    firebase_admin.initialize_app(cred, {
        'databaseURL': config['databaseURL']   
    })

# ✅ Setup Firestore and Realtime DB clients
firestore_db = firestore.client()
realtime_db = db

# =============================================================================


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


class ProfileForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(min=2, max=50)])
    student_id = StringField('ID', validators=[DataRequired(), Length(min=2, max=20)])
    department = StringField('Department', validators=[DataRequired(), Length(min=2, max=100)])
    bio = TextAreaField('Bio', validators=[Optional(), Length(max=200)])
    submit = SubmitField('Save Profile')
# =============================================================================
#  Routes
# =============================================================================

@app.route('/')
def home():
    """Redirects the root URL to the login page."""
    return redirect(url_for('login'))

# LOGIN
@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()

    if form.validate_on_submit():
        email = form.email.data
        password = form.password.data

        try:
            # 1️⃣ Sign in user with Firebase Auth
            user = auth.sign_in_with_email_and_password(email, password)

            # 2️⃣ Firestore: check in 'users' collection
            safe_email = email.replace(".", "_")
            doc_ref = firestore_db.collection("users").document(safe_email)
            doc = doc_ref.get()

            if not doc.exists:
                flash("User not found in Firestore. Contact admin.", "error")
                return redirect(url_for('login'))

            user_data = doc.to_dict()
            user_role = user_data.get("role", "Unknown")

            # 3️⃣ Check if profile is complete
            profile_fields = ["name", "id"]  # fields to check in Firestore
            profile_complete = all(
                field in user_data and user_data[field] for field in profile_fields
            )

            # 4️⃣ Set session info
            session['user_email'] = email
            session['user_role'] = user_role

            # 5️⃣ Redirect based on completeness
            if profile_complete:
                flash(f"Welcome back, {email}!", "success")
                return redirect(url_for('dashboard'))
            else:
                flash("Please complete your profile setup.", "info")
                return redirect(url_for('setup_profile'))

        except Exception as e:
            error_msg = str(e)
            if "INVALID_LOGIN_CREDENTIALS" in error_msg:
                flash("Invalid email or password.", "error")
            elif "EMAIL_NOT_FOUND" in error_msg:
                flash("No account found with this email.", "error")
            elif "INVALID_PASSWORD" in error_msg:
                flash("Incorrect password.", "error")
            else:
                flash("Login failed. Please try again.", "error")

    return render_template('login.html', form=form)




# SETUP PROFILE
@app.route('/setup_profile', methods=['GET', 'POST'])
def setup_profile():
    if 'user_email' not in session:
        flash('You must be logged in to setup profile.', 'error')
        return redirect(url_for('login'))

    form = ProfileForm()

    if form.validate_on_submit():
        # Get data from form
        name = form.name.data
        student_id = form.student_id.data
        department = form.department.data
        bio = form.bio.data

        # Get session info
        email = session['user_email']
        role = session.get('user_role', 'Student')  # Default to Student if missing
        safe_email = email.replace('.', '_')

        # Reference to users collection
        user_doc = firestore_db.collection("users").document(safe_email)

        # Data to save
        user_data = {
            'name': name,
            'id': student_id,
            'department': department,
            'bio': bio,
            'role': role
        }

        # Save profile data to Firestore
        user_doc.set(user_data, merge=True)

        flash('Profile saved successfully!', 'success')
        return redirect(url_for('dashboard'))

    # On GET or failed POST, render the form
    return render_template('setup_profile.html', form=form)



#DASHBOARD
@app.route('/dashboard')
def dashboard():
    """Renders the main dashboard for any logged-in user."""
    if 'user_role' not in session:
        flash('You must be logged in to view the dashboard.', 'error')
        return redirect(url_for('login'))
    
    return render_template('dashboard.html')



@app.route('/reset_password', methods=['POST'])
def reset_password():
    if 'user_email' not in session:
        return {"status": "error", "message": "You must be logged in to reset your password."}, 403

    try:
        email = session['user_email']
        auth.send_password_reset_email(email)
        return {"status": "success", "message": f"A password reset link has been sent to {email}."}
    except Exception as e:
        return {"status": "error", "message": f"Error sending reset email: {str(e)}"}, 500




@app.route('/update_profile', methods=['POST'])
def update_profile():
    if 'user_email' not in session:
        return jsonify({'error': 'User not logged in'}), 401

    data = request.get_json()
    name = data.get('name')
    user_id = data.get('id')
    department = data.get('department')
    bio = data.get('bio')

    try:
        safe_email = session['user_email'].replace('.', '_')
        user_doc = firestore_db.collection("users").document(safe_email)

        user_data = {
            'name': name,
            'id': user_id,
            'department': department,
            'bio': bio
        }


        user_doc.set(user_data, merge=True)
        return jsonify({'message': 'Profile updated successfully'}), 200

    except Exception as e:
        print("Error updating profile:", e)
        return jsonify({'error': str(e)}), 500




@app.route('/get_profile_data')
def get_profile_data():
    if 'user_email' not in session:
        return {'error': 'User not logged in'}, 401

    user_email = session['user_email']
    safe_email = user_email.replace('.', '_')  # Firestore doc names can’t contain '.'

    try:
        user_doc = firestore_db.collection("users").document(safe_email).get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            classroom_ids = user_data.get('classroom', [])  # list of ids (may be empty)

            classrooms = []
            for cid in classroom_ids:
                try:
                    class_ref = realtime_db.reference(f'classrooms/{cid}')
                    class_data = class_ref.get()
                    if class_data:
                        owner_email = class_data.get('owner', '')
                        owner_email = owner_email.replace('.', '_')
                        owner_doc = firestore_db.collection("users").document(owner_email).get()
                        if owner_doc.exists:
                            owner_name = owner_doc.to_dict().get('name', 'Unknown')    
                        classrooms.append({
                            'id': cid,
                            'name': class_data.get('classroomName', ''),
                            'owner': owner_name,
                            'ownerEmail': class_data.get('owner', ''),
                            'noOfStudents': class_data.get('noOfStudents',0),
                            'subjectCode': class_data.get('subjectCode', ''),
                            'createdDate': class_data.get('createdDate', ''),
                        })
                    else:
                        # If realtime entry was removed, skip or you can mark as missing
                        pass
                except Exception as e:
                    # log and continue
                    print(f"Error fetching classroom {cid} from RTDB:", e)

            return {
                'email': user_email,
                'role': user_data.get('role', ''),
                'name': user_data.get('name', ''),
                'userid': user_data.get('id', ''),
                'department': user_data.get('department', ''),
                'bio': user_data.get('bio', ''),
                'classrooms': classrooms
            }
        else:
            return {'error': 'User not found'}, 404
    except Exception as e:
        print("Error fetching user data:", e)
        return {'error': 'Failed to fetch user data'}, 500



@app.route('/search_users', methods=['GET'])
def search_users():
    # require login
    if 'user_email' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    raw_q = request.args.get('query', '').strip()
    if raw_q == '':
        return jsonify([])

    q = raw_q.lower()

    results = []

    try:
        students_col = firestore_db.collection('users')
        for doc in students_col.stream():
            data = doc.to_dict() or {}
            # normalize fields to avoid KeyErrors
            name = (data.get('name') or '').lower()
            userid = (data.get('userid') or data.get('id') or '').lower()

            if (q in name or q in userid) and doc.id.replace('_','.') != session.get('user_email',''):
                classroom_ids = data.get('classroom', [])  # list of ids (may be empty)
                classrooms = []
                for cid in classroom_ids:
                    try:
                        class_ref = realtime_db.reference(f'classrooms/{cid}')
                        class_data = class_ref.get()
                        if class_data:
                            if(class_data.get('owner')==doc.id.replace('_','.')):
                                classrooms.append({
                                    'id': cid,
                                    'name': class_data.get('classroomName', ''),
                                    'subjectCode': class_data.get('subjectCode', ''),
                                    'createdDate': class_data.get('createdDate', ''),
                                })
                        else:
                            # If realtime entry was removed, skip or you can mark as missing
                            pass
                    except Exception as e:
                        # log and continue
                        print(f"Error fetching classroom {cid} from RTDB:", e)
                        
                results.append({
                    'name': data.get('name', ''),
                    'email': data.get('email', ''),
                    'userid': data.get('userid') or data.get('id') or '',
                    'department': data.get('department', ''),
                    'bio': data.get('bio', ''),
                    'role': data.get('role',''),
                    'classrooms': classrooms
                })

        # optional: limit results
        # results = results[:50]

        return jsonify(results)

    except Exception as e:
        app.logger.exception("search_users failed")
        return jsonify({'error': 'Internal server error'}), 500



    

@app.route('/classroom/<classroom_id>')
def classroom_page(classroom_id):
    if 'user_role' not in session:
        return redirect(url_for('login'))
    return render_template('classroom.html', classroom_id=classroom_id)





@app.route('/courses/assessment')
def assessment():
    """Renders the assessment page."""
    try:
        return render_template('courses/assessment.html')
    except TemplateNotFound:
        abort(404)



@app.route('/courses/<course_name>')
def course(course_name):
    template_path = f'courses/{course_name}.html'
    try:
        return render_template(template_path)
    except TemplateNotFound:
        abort(404)



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



@app.route('/json/<path:filename>')
def serve_json(filename):
    """Serve JSON files from the templates/json directory."""
    return send_from_directory('templates/json', filename)



@app.route('/logout')
def logout():
    """Clears the user session."""
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))



@app.route('/create_classroom', methods=['POST'])
def create_classroom():
    try:
        data = request.get_json()
        name = data.get('name')
        subject = data.get('subject')
        user_email = session.get('user_email')

        if not user_email:
            return jsonify({'success': False, 'message': 'Not logged in'})

        ref = realtime_db.reference('classrooms')
        new_ref = ref.push({
            'classroomName': name,
            'subjectCode': subject,
            'owner': user_email,
            'createdDate': datetime.now().isoformat(),
            'noOfStudents': 0,
            'members': {},
            'joinRequests': {}
        })
        classroom={
            'id': new_ref.key,
            'name': name,
            'owner': "You",
            'ownerEmail': user_email,
            'noOfStudents': 0,
            'subjectCode': subject,
            'createdDate': datetime.now().strftime("%m/%d/%Y, %I:%M:%S %p")
        }
        classroom_id = new_ref.key    
        safe_email = user_email.replace('.', '_')
        user_classroom_ref = firestore_db.collection("users").document(safe_email)
        user_classroom_ref.set({
            'classroom': firestore.ArrayUnion([classroom_id])
        }, merge=True)
        

        return jsonify({'success': True, 'classroom': classroom})
    except Exception as e:
        return jsonify({'error': False, 'message': str(e)})
    
    

@app.route('/get_classroom/<classroom_id>')
def get_classroom(classroom_id):
    try:
        ref = realtime_db.reference(f'classrooms/{classroom_id}')
        data = ref.get()
        if not data:
            return jsonify({'error': 'Classroom not found'}), 404
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500




@app.route('/delete_classroom', methods=['POST'])
def delete_classroom():
    if 'user_email' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401

    data = request.get_json() or {}
    classroom_id = data.get('id')
    if not classroom_id:
        return jsonify({'success': False, 'message': 'Missing classroom id'}), 400

    user_email = session['user_email']
    safe_email = user_email.replace('.', '_')

    try:
        # 1️⃣ Get classroom data from Realtime DB
        class_ref = realtime_db.reference(f'classrooms/{classroom_id}')
        classroom_data = class_ref.get()

        if not classroom_data:
            return jsonify({'success': False, 'message': 'Classroom not found'}), 404

        members = classroom_data.get('members', {})

        # 2️⃣ Remove classroom from each member's Firestore document
        fs = firestore.client()
        for member_email_key in members.keys():
            # Convert back to normal email if needed
            email = member_email_key
            user_doc_ref = fs.collection('users').document(email)
            doc_snapshot = user_doc_ref.get()
            if doc_snapshot.exists:
                user_doc_ref.update({
                    'classroom': firestore.ArrayRemove([classroom_id])
                })

        # 3️⃣ Delete classroom from Realtime Database
        class_ref.delete()

        # 4️⃣ Remove classroom id from Firestore (owner)
        user_doc_ref = firestore_db.collection("users").document(safe_email)
        user_doc_ref.update({
            'classroom': firestore.ArrayRemove([classroom_id])
        })

        return jsonify({'success': True, 'message': 'Classroom deleted'}), 200

    except Exception as e:
        print("Error deleting classroom:", e)
        return jsonify({'success': False, 'message': str(e)}), 500

    


@app.route('/join_classroom/<classroom_id>', methods=['POST'])
def join_classroom(classroom_id):
    try:
        # Get logged-in user's email
        user_email = session.get('user_email')
        if not user_email:
            return jsonify({'error': 'User not logged in'}), 401

        # Make email RTDB-safe
        safe_email = user_email.replace('.', '_')

        # Reference to classroom join requests
        join_ref = db.reference(f'classrooms/{classroom_id}/joinRequests/{safe_email}')

        # Set value to True
        join_ref.set(True)

        return jsonify({'message': f'Join request sent for classroom {classroom_id}'})
    
    except Exception as e:
        print("Error in join_classroom:", e)
        return jsonify({'error': 'Internal server error'}), 500
    


    
@app.route('/join_classroom_by_code/<code>', methods=['POST'])
def join_classroom_by_code(code):
    try:
        user_email = session.get('user_email')
        if not user_email:
            return jsonify({'error': 'User not logged in'}), 401

        ref = realtime_db.reference('classrooms')
        all_classrooms = ref.get()

        if not all_classrooms:
            return jsonify({'error': 'No classrooms found'}), 404

        # 🔍 Find classroom whose ID starts with given code
        matched_classroom_id = None
        for cid in all_classrooms.keys():
            if cid.startswith(code):
                matched_classroom_id = cid
                break

        if not matched_classroom_id:
            return jsonify({'error': 'No classroom found with that code'}), 404

        # 🔹 Add user email to joinRequests of matched classroom
        join_ref = realtime_db.reference(f'classrooms/{matched_classroom_id}/joinRequests')
        safe_email = user_email.replace('.', '_')
        join_ref = db.reference(f'classrooms/{matched_classroom_id}/joinRequests/{safe_email}')
        # Set value to True
        join_ref.set(True)

        return jsonify({'message': f'Join request sent to classroom {matched_classroom_id}'}), 200

    except Exception as e:
        print("Error in join_classroom_by_code:", e)
        return jsonify({'error': 'Failed to send join request'}), 500
    



#CLASSROOM
@app.route('/get_join_requests/<classroom_id>', methods=['GET'])
def get_join_requests(classroom_id):
    try:
        # 1️⃣ Fetch join requests from Realtime DB
        join_req_ref = realtime_db.reference(f'classrooms/{classroom_id}/joinRequests')
        join_requests = join_req_ref.get() or {}

        if not join_requests:
            return jsonify([]), 200

        result = []

        # 2️⃣ Iterate through each email in joinRequests
        for email_key in join_requests.keys():
            # Convert email format back to normal if it’s stored as faculty1@insighteval_com
            email = email_key

            # 3️⃣ Search for this email in Firestore under User collection
            req_doc = firestore_db.collection("users").document(email).get()
            if req_doc.exists:
                req_name = req_doc.to_dict().get('name', 'Unknown')
            

            result.append({
                    'name':req_name ,
                    'email': email.replace('_', '.')
             })
           
        return jsonify(result), 200

    except Exception as e:
        print("Error fetching join requests:", str(e))
        return jsonify({'error': str(e)}), 500
    
    
    

@app.route('/reject_join_request', methods=['POST'])
def reject_join_request():
    try:
        data = request.get_json()
        classroom_id = data.get('classroom_id')
        email = data.get('email')

        if not classroom_id or not email:
            return jsonify({'error': 'Missing data'}), 400

        # Convert email to Firebase-safe key (replace '.' with '_')
        email_key = email.replace('.', '_')

        # Delete the join request from Realtime DB
        join_req_ref = realtime_db.reference(f'classrooms/{classroom_id}/joinRequests/{email_key}')
        join_req_ref.delete()

        return jsonify({'success': True, 'message': 'Join request rejected'}), 200

    except Exception as e:
        print("Error rejecting join request:", e)
        return jsonify({'error': str(e)}), 500



@app.route('/accept_join_request', methods=['POST'])
def accept_join_request():
    try:
        data = request.get_json()
        classroom_id = data.get('classroom_id')
        email = data.get('email')

        if not classroom_id or not email:
            return jsonify({'error': 'Missing data'}), 400

        email_key = email.replace('.', '_')
        classroom_ref = realtime_db.reference(f'classrooms/{classroom_id}')

        # 1️⃣ Move from joinRequests → members
        join_req_ref = classroom_ref.child(f'joinRequests/{email_key}')
        if join_req_ref.get() is None:
            return jsonify({'error': 'Join request not found'}), 404

        # Add to members node
        classroom_ref.child(f'members/{email_key}').set(True)

        # Delete from joinRequests
        join_req_ref.delete()

        # 2️⃣ Increment member count
        current_count = classroom_ref.child('noOfStudents').get() or 0
        classroom_ref.child('noOfStudents').set(current_count + 1)

        req_ref = firestore_db.collection("users").document(email_key)
        req_doc = req_ref.get()
        if req_doc.exists:
            req_ref.set({
            'classroom': firestore.ArrayUnion([classroom_id])
        }, merge=True)
        
        return jsonify({'success': True, 'message': 'Join request accepted'}), 200

    except Exception as e:
        print("Error accepting join request:", e)
        return jsonify({'error': str(e)}), 500
    



@app.route('/get_members/<classroom_id>', methods=['GET'])
def get_members(classroom_id):
    try:
        # 1️⃣ Fetch members from Realtime Database
        members_ref = realtime_db.reference(f'classrooms/{classroom_id}/members')
        members = members_ref.get() or {}

        if not members:
            return jsonify([]), 200

        firestore_db = firestore.client()
        result = []

        # 2️⃣ For each member email_key (stored as student1@insighteval_com)
        for email_key in members.keys():
            email = email_key.replace('_', '.')  # convert back to normal email format

            # 3️⃣ Check Firestore (faculty first, then students)
            doc_faculty = firestore_db.collection("users").document(email_key).get()
            if doc_faculty.exists:
                user_data = doc_faculty.to_dict()
                name = user_data.get('name', 'Unknown')
            
            result.append({
                'name': name,
                'email': email
            })

        return jsonify(result), 200

    except Exception as e:
        print("Error fetching members:", str(e))
        return jsonify({'error': str(e)}), 500
    

@app.route('/remove_member', methods=['POST'])
def remove_member():
    if 'user_email' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401

    data = request.get_json() or {}
    classroom_id = data.get('classroom_id')
    member_email = data.get('member_email')

    if not classroom_id or not member_email:
        return jsonify({'success': False, 'message': 'Missing data'}), 400

    safe_email = member_email.replace('.', '_')

    try:
        # 1️⃣ Remove member from Realtime Database
        class_ref = realtime_db.reference(f'classrooms/{classroom_id}/members/{safe_email}')
        class_ref.delete()

        # 2️⃣ Decrease number of students count
        class_meta_ref = realtime_db.reference(f'classrooms/{classroom_id}/noOfStudents')
        count = class_meta_ref.get() or 0
        if count > 0:
            class_meta_ref.set(count - 1)

        # 3️⃣ Remove classroom id from member's Firestore user doc
        fs = firestore.client()
        user_doc_ref = fs.collection('users').document(safe_email)
        if user_doc_ref.get().exists:
            user_doc_ref.update({
                'classroom': firestore.ArrayRemove([classroom_id])
            })

        return jsonify({'success': True, 'message': 'Member removed successfully'}), 200

    except Exception as e:
        print("Error removing member:", e)
        return jsonify({'success': False, 'message': str(e)}), 500






if __name__ == '__main__':
    app.run(debug=True)