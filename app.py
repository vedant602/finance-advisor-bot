import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, request, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from google import genai

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'my-super-secret-key-12345')

DB_NAME = "finance.db"

# --- Database Setup ---
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS incomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            source TEXT NOT NULL,
            date TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            description TEXT,
            date TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

# --- Gemini Setup ---
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
ai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# --- Routes ---
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM users WHERE email = ? OR username = ?", (email, username))
        if cursor.fetchone():
            conn.close()
            flash("Username or Email already exists.", "danger")
            return redirect(url_for('register'))
            
        hashed_pw = generate_password_hash(password)
        cursor.execute("INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                       (username, email, hashed_pw))
        conn.commit()
        conn.close()
        
        flash("Registration successful! Please login.", "success")
        return redirect(url_for('login'))
        
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = cursor.fetchone()
        conn.close()
        
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid email or password.", "danger")
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out successfully.", "info")
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM incomes WHERE user_id = ? ORDER BY id DESC", (user_id,))
    incomes = cursor.fetchall()
    
    cursor.execute("SELECT * FROM expenses WHERE user_id = ? ORDER BY id DESC", (user_id,))
    expenses = cursor.fetchall()
    conn.close()
    
    total_income = sum(inc['amount'] for inc in incomes)
    total_expense = sum(exp['amount'] for exp in expenses)
    balance = total_income - total_expense
    
    return render_template('dashboard.html',
                           username=session.get('username'),
                           incomes=incomes,
                           expenses=expenses,
                           total_income=total_income,
                           total_expense=total_expense,
                           balance=balance)

@app.route('/add-income', methods=['POST'])
def add_income():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    amount = float(request.form.get('amount'))
    source = request.form.get('source')
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO incomes (user_id, amount, source, date) VALUES (?, ?, ?, ?)",
                   (session['user_id'], amount, source, date_str))
    conn.commit()
    conn.close()
    
    flash("Income added successfully!", "success")
    return redirect(url_for('dashboard'))

@app.route('/add-expense', methods=['POST'])
def add_expense():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    amount = float(request.form.get('amount'))
    category = request.form.get('category')
    description = request.form.get('description', '')
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO expenses (user_id, amount, category, description, date) VALUES (?, ?, ?, ?, ?)",
                   (session['user_id'], amount, category, description, date_str))
    conn.commit()
    conn.close()
    
    flash("Expense added successfully!", "success")
    return redirect(url_for('dashboard'))

@app.route('/ai-insights')
def ai_insights():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM incomes WHERE user_id = ?", (user_id,))
    incomes = cursor.fetchall()
    
    cursor.execute("SELECT * FROM expenses WHERE user_id = ?", (user_id,))
    expenses = cursor.fetchall()
    conn.close()
    
    total_income = sum(inc['amount'] for inc in incomes)
    total_expense = sum(exp['amount'] for exp in expenses)
    
    expense_summary = {}
    for exp in expenses:
        expense_summary[exp['category']] = expense_summary.get(exp['category'], 0) + exp['amount']
        
    prompt = f"""
    You are a Personal Finance Advisor AI. Analyze this user financial data:
    - Total Income: ${total_income}
    - Total Expenses: ${total_expense}
    - Expense Breakdown by Category: {expense_summary}
    
    Provide:
    1. A short analysis of spending habits.
    2. Overspending alerts or warnings.
    3. Three actionable personalized tips to increase monthly savings.
    4. A recommended budget breakdown for next month.
    Format cleanly with clear headings and bullet points.
    """
    
    ai_response = ""
    if ai_client:
        try:
            response = ai_client.models.generate_content(
                model="gemini-3.8-flash",
                contents=prompt
            )
            ai_response = response.text
        except Exception as e:
            ai_response = f"Could not generate AI insights: {str(e)}"
    else:
        ai_response = "Gemini API key is missing. Please check your .env file."
        
    return render_template('ai_insights.html', insights=ai_response)

@app.route('/api/chat', methods=['POST'])
def api_chat():
    if 'user_id' not in session:
        return {"error": "Unauthorized"}, 401
        
    data = request.get_json()
    user_message = data.get('message', '')
    
    user_id = session['user_id']
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM incomes WHERE user_id = ?", (user_id,))
    incomes = cursor.fetchall()
    
    cursor.execute("SELECT * FROM expenses WHERE user_id = ?", (user_id,))
    expenses = cursor.fetchall()
    conn.close()
    
    total_income = sum(inc['amount'] for inc in incomes)
    total_expense = sum(exp['amount'] for exp in expenses)
    expense_summary = {}
    for exp in expenses:
        expense_summary[exp['category']] = expense_summary.get(exp['category'], 0) + exp['amount']
        
    chat_prompt = f"""
    You are a Personal Finance Advisor AI assisting a user.
    User's Financial Profile:
    - Total Income: ${total_income}
    - Total Expenses: ${total_expense}
    - Expense Breakdown: {expense_summary}
    
    User Query: {user_message}
    
    Provide a helpful, tailored, and encouraging answer taking their financial profile, daily schedule, and personal goals into account.
    """
    
    if ai_client:
        try:
            response = ai_client.models.generate_content(
                model="gemini-3.8-flash",
                contents=chat_prompt
            )
            return {"reply": response.text}
        except Exception as e:
            return {"error": f"AI Error: {str(e)}"}, 500
    else:
        return {"error": "Gemini API Key missing."}, 400

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)