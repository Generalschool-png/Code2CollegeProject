from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import sqlite3
import os

app = Flask(__name__)
app.secret_key = 'your-secret-key-123'  # Change this in production!

# Database setup
def get_db():
    db = sqlite3.connect('bank.db')
    db.row_factory = sqlite3.Row
    return db

def init_db():
    if not os.path.exists('bank.db'):
        db = get_db()
        cursor = db.cursor()
        
        # Create tables
        cursor.execute('''
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                pin_hash TEXT NOT NULL,
                full_name TEXT NOT NULL,
                email TEXT,
                phone TEXT,
                is_admin BOOLEAN DEFAULT 0
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                account_number TEXT UNIQUE NOT NULL,
                balance REAL DEFAULT 0.0,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                transaction_type TEXT NOT NULL,
                description TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(account_id) REFERENCES accounts(id)
            )
        ''')
        
        # Create admin user
        admin_pin = generate_password_hash('1234')
        cursor.execute('''
            INSERT INTO users (username, pin_hash, full_name, is_admin)
            VALUES (?, ?, ?, ?)
        ''', ('admin', admin_pin, 'Administrator', 1))
        
        db.commit()
        db.close()

# Initialize database
init_db()

# Helper functions
def generate_account_number(user_id):
    return f"AC{user_id:08d}"

def get_user_accounts(user_id):
    db = get_db()
    accounts = db.execute('''
        SELECT id, account_number, balance 
        FROM accounts 
        WHERE user_id = ?
    ''', (user_id,)).fetchall()
    db.close()
    return accounts

# Routes
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        pin = request.form['pin']
        
        db = get_db()
        user = db.execute('''
            SELECT id, username, pin_hash, full_name, is_admin 
            FROM users 
            WHERE username = ?
        ''', (username,)).fetchone()
        db.close()
        
        if user and check_password_hash(user['pin_hash'], pin):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['full_name'] = user['full_name']
            session['is_admin'] = user['is_admin']
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or PIN', 'danger')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        pin = request.form['pin']
        full_name = request.form['full_name']
        email = request.form.get('email', '')
        phone = request.form.get('phone', '')
        
        try:
            db = get_db()
            pin_hash = generate_password_hash(pin)
            db.execute('''
                INSERT INTO users (username, pin_hash, full_name, email, phone)
                VALUES (?, ?, ?, ?, ?)
            ''', (username, pin_hash, full_name, email, phone))
            
            # Create account for new user
            user_id = db.lastrowid
            account_number = generate_account_number(user_id)
            db.execute('''
                INSERT INTO accounts (user_id, account_number)
                VALUES (?, ?)
            ''', (user_id, account_number))
            
            db.commit()
            db.close()
            flash('Account created successfully!', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            db.close()
            flash('Username already exists', 'danger')
    
    return render_template('register.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    accounts = get_user_accounts(session['user_id'])
    
    # Get recent transactions for the first account (if exists)
    transactions = []
    if accounts:
        transactions = db.execute('''
            SELECT amount, transaction_type, description, timestamp
            FROM transactions
            WHERE account_id = ?
            ORDER BY timestamp DESC
            LIMIT 5
        ''', (accounts[0]['id'],)).fetchall()
    
    db.close()
    
    return render_template('dashboard.html', 
                         accounts=accounts,
                         transactions=transactions)

@app.route('/deposit', methods=['GET', 'POST'])
def deposit():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    accounts = get_user_accounts(session['user_id'])
    if not accounts:
        flash('No accounts found', 'danger')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        account_id = request.form['account_id']
        amount = float(request.form['amount'])
        
        if amount <= 0:
            flash('Amount must be positive', 'danger')
            return redirect(url_for('deposit'))
        
        db = get_db()
        try:
            # Update balance
            db.execute('''
                UPDATE accounts
                SET balance = balance + ?
                WHERE id = ?
            ''', (amount, account_id))
            
            # Record transaction
            db.execute('''
                INSERT INTO transactions (account_id, amount, transaction_type, description)
                VALUES (?, ?, ?, ?)
            ''', (account_id, amount, 'deposit', 'Online deposit'))
            
            db.commit()
            flash(f'${amount:.2f} deposited successfully', 'success')
        except:
            db.rollback()
            flash('Transaction failed', 'danger')
        finally:
            db.close()
        
        return redirect(url_for('dashboard'))
    
    return render_template('deposit.html', accounts=accounts)

@app.route('/withdraw', methods=['GET', 'POST'])
def withdraw():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    accounts = get_user_accounts(session['user_id'])
    if not accounts:
        flash('No accounts found', 'danger')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        account_id = request.form['account_id']
        amount = float(request.form['amount'])
        
        db = get_db()
        account = db.execute('SELECT balance FROM accounts WHERE id = ?', (account_id,)).fetchone()
        
        if amount <= 0:
            flash('Amount must be positive', 'danger')
        elif amount > account['balance']:
            flash('Insufficient funds', 'danger')
        else:
            try:
                # Update balance
                db.execute('''
                    UPDATE accounts
                    SET balance = balance - ?
                    WHERE id = ?
                ''', (amount, account_id))
                
                # Record transaction
                db.execute('''
                    INSERT INTO transactions (account_id, amount, transaction_type, description)
                    VALUES (?, ?, ?, ?)
                ''', (account_id, amount, 'withdrawal', 'Online withdrawal'))
                
                db.commit()
                flash(f'${amount:.2f} withdrawn successfully', 'success')
            except:
                db.rollback()
                flash('Transaction failed', 'danger')
            finally:
                db.close()
            
            return redirect(url_for('dashboard'))
    
    return render_template('withdraw.html', accounts=accounts)

@app.route('/transfer', methods=['GET', 'POST'])
def transfer():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    accounts = get_user_accounts(session['user_id'])
    if not accounts:
        flash('No accounts found', 'danger')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        from_account_id = request.form['from_account_id']
        to_account_number = request.form['to_account_number']
        amount = float(request.form['amount'])
        
        db = get_db()
        
        # Check source account balance
        from_account = db.execute('''
            SELECT balance FROM accounts WHERE id = ?
        ''', (from_account_id,)).fetchone()
        
        # Check destination account
        to_account = db.execute('''
            SELECT id FROM accounts WHERE account_number = ?
        ''', (to_account_number,)).fetchone()
        
        if amount <= 0:
            flash('Amount must be positive', 'danger')
        elif amount > from_account['balance']:
            flash('Insufficient funds', 'danger')
        elif not to_account:
            flash('Destination account not found', 'danger')
        else:
            try:
                # Begin transaction
                db.execute('BEGIN TRANSACTION')
                
                # Withdraw from source
                db.execute('''
                    UPDATE accounts
                    SET balance = balance - ?
                    WHERE id = ?
                ''', (amount, from_account_id))
                
                # Deposit to destination
                db.execute('''
                    UPDATE accounts
                    SET balance = balance + ?
                    WHERE id = ?
                ''', (amount, to_account['id']))
                
                # Record transactions
                db.execute('''
                    INSERT INTO transactions (account_id, amount, transaction_type, description)
                    VALUES (?, ?, ?, ?)
                ''', (from_account_id, amount, 'transfer', f'Transfer to {to_account_number}'))
                
                db.execute('''
                    INSERT INTO transactions (account_id, amount, transaction_type, description)
                    VALUES (?, ?, ?, ?)
                ''', (to_account['id'], amount, 'transfer', f'Transfer from {from_account_id}'))
                
                db.commit()
                flash(f'${amount:.2f} transferred successfully', 'success')
            except:
                db.rollback()
                flash('Transfer failed', 'danger')
            finally:
                db.close()
            
            return redirect(url_for('dashboard'))
    
    return render_template('transfer.html', accounts=accounts)

@app.route('/transactions')
def transactions():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    account_id = request.args.get('account_id')
    if not account_id:
        flash('No account specified', 'danger')
        return redirect(url_for('dashboard'))
    
    db = get_db()
    
    # Verify user owns this account
    account = db.execute('''
        SELECT a.id, a.account_number 
        FROM accounts a
        JOIN users u ON a.user_id = u.id
        WHERE a.id = ? AND u.id = ?
    ''', (account_id, session['user_id'])).fetchone()
    
    if not account:
        db.close()
        flash('Account not found', 'danger')
        return redirect(url_for('dashboard'))
    
    # Get transactions
    transactions = db.execute('''
        SELECT amount, transaction_type, description, timestamp
        FROM transactions
        WHERE account_id = ?
        ORDER BY timestamp DESC
    ''', (account_id,)).fetchall()
    
    db.close()
    
    return render_template('transactions.html', 
                         account=account,
                         transactions=transactions)

@app.route('/admin')
def admin_dashboard():
    if 'user_id' not in session or not session.get('is_admin'):
        flash('Unauthorized access', 'danger')
        return redirect(url_for('dashboard'))
    
    db = get_db()
    
    # Get all accounts
    accounts = db.execute('''
        SELECT a.id, a.account_number, a.balance, u.full_name
        FROM accounts a
        JOIN users u ON a.user_id = u.id
        ORDER BY a.id DESC
    ''').fetchall()
    
    # Get recent transactions
    transactions = db.execute('''
        SELECT t.amount, t.transaction_type, t.description, t.timestamp,
               a.account_number, u.full_name
        FROM transactions t
        JOIN accounts a ON t.account_id = a.id
        JOIN users u ON a.user_id = u.id
        ORDER BY t.timestamp DESC
        LIMIT 10
    ''').fetchall()
    
    db.close()
    
    return render_template('admin_dashboard.html',
                         accounts=accounts,
                         transactions=transactions)

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)