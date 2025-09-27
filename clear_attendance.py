import sqlite3

def clear_attendance_records():
    try:
        # Connect to the database
        conn = sqlite3.connect('attendance.db')
        cursor = conn.cursor()
        
        # Delete all records from attendance table
        cursor.execute('DELETE FROM attendance')
        
        # Get the number of deleted records
        deleted_count = cursor.rowcount
        
        # Commit the changes
        conn.commit()
        
        print(f"Successfully deleted {deleted_count} attendance records from the database.")
        
        # Verify the table is empty
        cursor.execute('SELECT COUNT(*) FROM attendance')
        remaining_count = cursor.fetchone()[0]
        print(f"Remaining attendance records: {remaining_count}")
        
    except Exception as e:
        print(f"Error clearing attendance records: {str(e)}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    clear_attendance_records()