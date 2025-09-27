from flask import Flask, render_template, request, jsonify, send_file, g
from datetime import datetime, timedelta
import sqlite3
import csv
import io
import pandas as pd
import random
from collections import defaultdict
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, 
    template_folder='templates',
    static_folder='static',
    static_url_path='/static')
app.debug = True

DATABASE = 'attendance.db'
SECURITY_KEY = os.environ.get("SECURITY_KEY", "atlas123")

def init_db():
    conn = None
    try:
        conn = sqlite3.connect('attendance.db')
        conn.execute("PRAGMA foreign_keys = ON")
        c = conn.cursor()
        
        c.execute("DROP TABLE IF EXISTS attendance")
        c.execute("DROP TABLE IF EXISTS members")
        
        c.execute('''CREATE TABLE members
                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     member_id TEXT NOT NULL UNIQUE,
                     name TEXT NOT NULL,
                     gender TEXT NOT NULL,
                     age INTEGER NOT NULL,
                     membership_plan TEXT NOT NULL,
                     join_date DATE NOT NULL)''')
                     
        c.execute('''CREATE TABLE attendance
                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     member_id TEXT NOT NULL,
                     check_in DATETIME NOT NULL,
                     check_out DATETIME,
                     date DATE NOT NULL,
                     FOREIGN KEY (member_id) REFERENCES members(member_id),
                     UNIQUE(member_id, date))''')
        
        sample_members = [
            ('M001', 'John Smith', 'Male', 28, 'Premium', '2025-01-01'),
            ('M002', 'Mary Johnson', 'Female', 35, 'Basic', '2025-01-15'),
            ('M003', 'Peter Brown', 'Male', 42, 'Annual', '2025-02-01'),
            ('M004', 'Sarah Wilson', 'Female', 23, 'Premium', '2025-02-15'),
            ('M005', 'Mike Davis', 'Male', 31, 'Basic', '2025-03-01')
        ]
        
        c.executemany('INSERT INTO members (member_id, name, gender, age, membership_plan, join_date) VALUES (?, ?, ?, ?, ?, ?)',
                    sample_members)
        
        conn.commit()
        print("Database initialized successfully!")
        
    except Exception as e:
        print(f"Error initializing database: {str(e)}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
    return db

def init_db_if_needed():
    try:
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='members'")
        if not cursor.fetchone():
            init_db()
        else:
            cursor.execute("SELECT COUNT(*) FROM members")
            if cursor.fetchone()[0] == 0:
                init_db()
    except Exception as e:
        print(f"Error checking/initializing database: {e}")
        init_db()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

@app.before_request
def setup():
    init_db_if_needed()

@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/checkin')
def checkin():
    return render_template('checkin.html')

@app.route('/admin')
def admin():
    return render_template('admin.html')

@app.route('/analytics')
def analytics():
    try:
        conn = get_db()
        years = pd.read_sql_query('''
            SELECT DISTINCT strftime('%Y', date) as year
            FROM attendance
            ORDER BY year DESC
        ''', conn)
        return render_template('analytics.html',
                             years=years['year'].tolist(),
                             current_year=datetime.now().year)
    except Exception as e:
        return render_template('analytics.html',
                             years=[str(datetime.now().year)],
                             current_year=datetime.now().year)

@app.route('/api/member-monthly-stats')
def get_member_monthly_stats():
    try:
        member_id = request.args.get('member_id')
        name = request.args.get('name')
        year = int(request.args.get('year', datetime.now().year))
        month = int(request.args.get('month', datetime.now().month))
        
        if not (member_id or name):
            return jsonify({'error': 'Member ID or Name is required'}), 400
            
        conn = get_db()
        
        last_day = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
        total_days = last_day.day
        
        where_conditions = []
        params = []
        
        if member_id:
            where_conditions.append("m.member_id = ?")
            params.append(member_id)
        if name:
            where_conditions.append("m.name LIKE ?")
            params.append(f"%{name}%")
        
        where_clause = " AND ".join(where_conditions)
        
        query = f"""
            SELECT 
                m.member_id,
                m.name,
                m.gender,
                m.membership_plan,
                COUNT(DISTINCT a.date) as days_attended,
                AVG(
                    CASE 
                        WHEN a.check_out IS NOT NULL 
                        THEN (julianday(a.check_out) - julianday(a.check_in)) * 24 
                        ELSE NULL 
                    END
                ) as avg_hours_per_visit
            FROM members m
            LEFT JOIN attendance a ON m.member_id = a.member_id
            WHERE {where_clause}
            AND strftime('%Y', a.date) = ?
            AND strftime('%m', a.date) = ?
            GROUP BY m.member_id, m.name, m.gender, m.membership_plan
        """
        
        params.extend([str(year), f"{month:02d}"])
        df = pd.read_sql_query(query, conn, params=params)
        
        if df.empty:
            return jsonify({'error': 'No member found'}), 404
            
        daily_query = f"""
            SELECT 
                strftime('%d', a.date) as day,
                COUNT(*) as visits
            FROM attendance a
            JOIN members m ON a.member_id = m.member_id
            WHERE {where_clause}
            AND strftime('%Y', a.date) = ?
            AND strftime('%m', a.date) = ?
            GROUP BY strftime('%d', a.date)
            ORDER BY day
        """
        
        daily_data = pd.read_sql_query(daily_query, conn, params=params)
        
        member_stats = df.iloc[0]
        days_attended = member_stats['days_attended']
        missed_days = total_days - days_attended
        attendance_percentage = (days_attended / total_days) * 100
        
        response = {
            'member': {
                'member_id': member_stats['member_id'],
                'name': member_stats['name'],
                'gender': member_stats['gender'],
                'membership_plan': member_stats['membership_plan']
            },
            'statistics': {
                'days_attended': int(days_attended),
                'total_possible_days': total_days,
                'missed_days': int(missed_days),
                'attendance_percentage': round(attendance_percentage, 1),
                'avg_hours_per_visit': round(float(member_stats['avg_hours_per_visit'] or 0), 1)
            },
            'chart_data': {
                'labels': [str(day).zfill(2) for day in range(1, total_days + 1)],
                'datasets': [{
                    'label': 'Daily Visits',
                    'data': [int(daily_data[daily_data['day'] == str(day).zfill(2)]['visits'].iloc[0]) 
                            if not daily_data[daily_data['day'] == str(day).zfill(2)].empty else 0 
                            for day in range(1, total_days + 1)],
                    'backgroundColor': 'rgba(54, 162, 235, 0.5)',
                    'borderColor': 'rgba(54, 162, 235, 1)',
                    'borderWidth': 1
                }]
            }
        }
        
        return jsonify(response)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/check-in', methods=['POST'])
def check_in():
    try:
        data = request.json
        name = data.get('name')
        member_id = data.get('member_id')
        now = datetime.now()
        
        if not name or not member_id:
            return jsonify({"error": "Name and Member ID are required!"}), 400
        
        # Validate member ID format (7 digits)
        if not member_id.isdigit() or len(member_id) != 7:
            return jsonify({"error": "Member ID must be exactly 7 digits!"}), 400
        
        db = get_db()
        c = db.cursor()
        
        # Check if member exists, if not create new member
        c.execute('SELECT member_id FROM members WHERE member_id = ?', (member_id,))
        if not c.fetchone():
            # Create new member with default values
            c.execute('''INSERT INTO members (member_id, name, gender, age, membership_plan, join_date)
                        VALUES (?, ?, ?, ?, ?, ?)''', 
                        (member_id, name, 'Not Specified', 25, 'Basic', now.date()))
        
        # Check if member has any check-in record for today
        c.execute('''SELECT id, check_out FROM attendance 
                    WHERE member_id = ? AND date = ?''', 
                    (member_id, now.date()))
        existing = c.fetchone()
        
        if existing:
            if existing['check_out'] is None:
                return jsonify({"error": "You are already checked in for today!"}), 400
            
            # If there's an existing record and it's checked out, update it
            c.execute('''UPDATE attendance 
                        SET check_in = ?, check_out = NULL 
                        WHERE id = ?''', 
                        (now, existing['id']))
        else:
            # Create new record if none exists
            c.execute('''INSERT INTO attendance (member_id, check_in, date)
                        VALUES (?, ?, ?)''', 
                        (member_id, now, now.date()))
        
        db.commit()
        return jsonify({"message": "Check-in successful!"})
    except Exception as e:
        return jsonify({"error": "Failed to process check-in"}), 500

@app.route('/check-out', methods=['POST'])
def check_out():
    try:
        data = request.json
        member_id = data.get('member_id')
        
        if not member_id:
            return jsonify({"error": "Member ID is required!"}), 400
        
        # Validate member ID format (7 digits)
        if not member_id.isdigit() or len(member_id) != 7:
            return jsonify({"error": "Member ID must be exactly 7 digits!"}), 400
            
        now = datetime.now()
        
        db = get_db()
        c = db.cursor()
        c.execute('''UPDATE attendance 
                     SET check_out = ? 
                     WHERE member_id = ? 
                     AND date = ? 
                     AND check_out IS NULL''', (now, member_id, now.date()))
        
        if c.rowcount == 0:
            return jsonify({"error": "No active check-in found for this Member ID"}), 404
            
        db.commit()
        
        return jsonify({"message": "Check-out successful!"})
    except Exception as e:
        return jsonify({"error": "Failed to process check-out"}), 500

@app.route('/verify-key', methods=['POST'])
def verify_key():
    try:
        data = request.json
        provided_key = data.get('key')
        print(f"Provided key: '{provided_key}', Expected key: '{SECURITY_KEY}'")
        
        if provided_key == SECURITY_KEY:
            return jsonify({"valid": True})
        return jsonify({"valid": False})
    except Exception as e:
        print(f"Error in verify_key: {str(e)}")
        return jsonify({"valid": False, "error": str(e)}), 500

@app.route('/get-records', methods=['GET'])
def get_records():
    try:
        db = get_db()
        records = pd.read_sql_query('''
            SELECT a.id, m.name, a.member_id, a.check_in, a.check_out, a.date
            FROM attendance a
            JOIN members m ON a.member_id = m.member_id
            ORDER BY a.date DESC, a.check_in DESC
        ''', db)
        
        records_list = []
        for _, record in records.iterrows():
            records_list.append({
                "id": record['id'],
                "name": record['name'],
                "member_id": record['member_id'],
                "check_in": record['check_in'],
                "check_out": record['check_out'] if pd.notna(record['check_out']) else "Pending",
                "date": record['date']
            })
        
        return jsonify(records_list)
    except Exception as e:
        return jsonify({"error": "Failed to fetch records"}), 500

@app.route('/download-csv')
def download_csv():
    try:
        db = get_db()
        records = pd.read_sql_query('''
            SELECT a.id, m.name, a.member_id, a.check_in, a.check_out, a.date
            FROM attendance a
            JOIN members m ON a.member_id = m.member_id
            ORDER BY a.date DESC, a.check_in DESC
        ''', db)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['ID', 'Name', 'Member ID', 'Check-in Time', 'Check-out Time', 'Date'])
        
        for _, record in records.iterrows():
            writer.writerow([
                record['id'],
                record['name'],
                record['member_id'],
                record['check_in'],
                record['check_out'] if pd.notna(record['check_out']) else 'Pending',
                record['date']
            ])

        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'attendance_{datetime.now().strftime("%Y%m%d")}.csv'
        )
    except Exception as e:
        return jsonify({"error": "Failed to generate CSV"}), 500

@app.route('/delete-record/<int:record_id>', methods=['DELETE'])
def delete_record(record_id):
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute('DELETE FROM attendance WHERE id = ?', (record_id,))
        db.commit()
        return jsonify({"message": "Record deleted successfully!"})
    except Exception as e:
        return jsonify({"error": "Failed to delete record"}), 500

if __name__ == '__main__':
    init_db()
    app.run(debug=True)