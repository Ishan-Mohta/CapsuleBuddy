from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime, timedelta
import requests
import schedule
import threading
import time
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend-backend communication

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///capsulebuddy.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    conditions = db.Column(db.Text)  # Comma-separated health conditions
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    reminders = db.relationship('Reminder', backref='user', lazy=True)

class Medicine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    side_effects = db.Column(db.Text)  # Comma-separated side effects
    interactions = db.Column(db.Text)  # Comma-separated interactions with other medicines
    
    reminders = db.relationship('Reminder', backref='medicine', lazy=True)

class Reminder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    medicine_id = db.Column(db.Integer, db.ForeignKey('medicine.id'), nullable=False)
    dosage = db.Column(db.String(50), nullable=False)  # e.g., "1 tablet", "5ml"
    frequency = db.Column(db.String(50), nullable=False)  # e.g., "daily", "twice daily"
    specific_times = db.Column(db.Text)  # Comma-separated times (e.g., "08:00,20:00")
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Create tables
with app.app_context():
    db.create_all()

# Medication Safety Check (using OpenFDA API)
def check_medicine_safety(medicine_name, user_conditions, current_medications):
    """
    Check if a medicine is safe for a user given their conditions and current medications
    This uses the OpenFDA API for drug information
    """
    try:
        # API call to OpenFDA for drug information
        api_url = f"https://api.fda.gov/drug/label.json?search=openfda.brand_name:{medicine_name}&limit=1"
        response = requests.get(api_url)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('results'):
                drug_info = data['results'][0]
                warnings = drug_info.get('warnings', [])
                contraindications = drug_info.get('contraindications', [])
                
                # Simple safety check based on user conditions
                safety_issues = []
                for condition in user_conditions:
                    if condition.lower() in str(contraindications).lower():
                        safety_issues.append(f"Not recommended for patients with {condition}")
                
                return {
                    'safe': len(safety_issues) == 0,
                    'issues': safety_issues,
                    'warnings': warnings
                }
        
        return {'safe': True, 'issues': [], 'warnings': []}
    except:
        return {'safe': True, 'issues': [], 'warnings': []}

# Reminder system
def check_reminders():
    """
    Check for reminders that need to be sent
    This function runs periodically
    """
    with app.app_context():
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        current_date = now.date()
        
        # Get all active reminders
        reminders = Reminder.query.filter_by(active=True).all()
        
        for reminder in reminders:
            # Check if reminder is for today
            if reminder.start_date.date() <= current_date and (reminder.end_date is None or reminder.end_date.date() >= current_date):
                times = reminder.specific_times.split(',')
                
                # Check if current time matches any of the reminder times
                if current_time in times:
                    user = User.query.get(reminder.user_id)
                    medicine = Medicine.query.get(reminder.medicine_id)
                    
                    # In a real application, you would send a notification here
                    print(f"Reminder for {user.name}: Take {reminder.dosage} of {medicine.name} at {current_time}")
                    
                    # You would integrate with a notification service (email, push, SMS) here

# Schedule the reminder checker to run every minute
scheduler = BackgroundScheduler()
scheduler.add_job(func=check_reminders, trigger="interval", minutes=1)
scheduler.start()

# API Routes
@app.route('/api/register', methods=['POST'])
def register():
    """User registration endpoint"""
    data = request.json
    try:
        user = User(
            name=data['name'],
            email=data['email'],
            password=data['password'],  # In production, hash this password!
            conditions=','.join(data.get('conditions', []))
        )
        db.session.add(user)
        db.session.commit()
        
        return jsonify({'message': 'User created successfully', 'user_id': user.id}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/login', methods=['POST'])
def login():
    """User login endpoint"""
    data = request.json
    user = User.query.filter_by(email=data['email'], password=data['password']).first()
    
    if user:
        return jsonify({
            'message': 'Login successful',
            'user_id': user.id,
            'name': user.name,
            'conditions': user.conditions.split(',') if user.conditions else []
        }), 200
    else:
        return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/medicine', methods=['POST'])
def add_medicine():
    """Add a new medicine to the database"""
    data = request.json
    try:
        medicine = Medicine(
            name=data['name'],
            description=data.get('description', ''),
            side_effects=','.join(data.get('side_effects', [])),
            interactions=','.join(data.get('interactions', []))
        )
        db.session.add(medicine)
        db.session.commit()
        
        return jsonify({'message': 'Medicine added successfully', 'medicine_id': medicine.id}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/reminder', methods=['POST'])
def add_reminder():
    """Add a new reminder for a user"""
    data = request.json
    try:
        # Check if the medicine is safe for the user
        user = User.query.get(data['user_id'])
        user_conditions = user.conditions.split(',') if user.conditions else []
        
        # In a real application, you would get current medications from the database
        current_medications = []  
        
        safety_check = check_medicine_safety(
            Medicine.query.get(data['medicine_id']).name,
            user_conditions,
            current_medications
        )
        
        if not safety_check['safe']:
            return jsonify({
                'warning': 'This medicine may not be safe for you',
                'issues': safety_check['issues'],
                'warnings': safety_check['warnings']
            }), 200
        
        reminder = Reminder(
            user_id=data['user_id'],
            medicine_id=data['medicine_id'],
            dosage=data['dosage'],
            frequency=data['frequency'],
            specific_times=','.join(data['specific_times']),
            start_date=datetime.strptime(data['start_date'], '%Y-%m-%d'),
            end_date=datetime.strptime(data['end_date'], '%Y-%m-%d') if data.get('end_date') else None
        )
        db.session.add(reminder)
        db.session.commit()
        
        return jsonify({
            'message': 'Reminder added successfully',
            'reminder_id': reminder.id,
            'safety_check': safety_check
        }), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/reminders/<int:user_id>', methods=['GET'])
def get_reminders(user_id):
    """Get all reminders for a user"""
    reminders = Reminder.query.filter_by(user_id=user_id).all()
    result = []
    
    for reminder in reminders:
        medicine = Medicine.query.get(reminder.medicine_id)
        result.append({
            'id': reminder.id,
            'medicine_name': medicine.name,
            'dosage': reminder.dosage,
            'frequency': reminder.frequency,
            'times': reminder.specific_times.split(','),
            'start_date': reminder.start_date.strftime('%Y-%m-%d'),
            'end_date': reminder.end_date.strftime('%Y-%m-%d') if reminder.end_date else None,
            'active': reminder.active
        })
    
    return jsonify({'reminders': result}), 200

@app.route('/api/check-safety', methods=['POST'])
def check_safety():
    """Check if a medicine is safe for a user"""
    data = request.json
    user = User.query.get(data['user_id'])
    medicine = Medicine.query.get(data['medicine_id'])
    
    user_conditions = user.conditions.split(',') if user.conditions else []
    current_medications = []  # In a real app, you'd get this from the database
    
    safety_info = check_medicine_safety(
        medicine.name,
        user_conditions,
        current_medications
    )
    
    return jsonify(safety_info), 200

@app.route('/api/medicine/search/<name>', methods=['GET'])
def search_medicine(name):
    """Search for medicines by name"""
    medicines = Medicine.query.filter(Medicine.name.ilike(f'%{name}%')).all()
    result = []
    
    for medicine in medicines:
        result.append({
            'id': medicine.id,
            'name': medicine.name,
            'description': medicine.description,
            'side_effects': medicine.side_effects.split(',') if medicine.side_effects else [],
            'interactions': medicine.interactions.split(',') if medicine.interactions else []
        })
    
    return jsonify({'medicines': result}), 200

if __name__ == '__main__':
    app.run(debug=True, port=5000)