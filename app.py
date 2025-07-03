from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import boto3
import uuid
import os
from dotenv import load_dotenv
import json
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Load environment variables
load_dotenv()

# App Initialization
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'secret')

# AWS Config
REGION = os.getenv('AWS_REGION_NAME', 'us-east-1')
USERS_TABLE_NAME = os.getenv('USERS_TABLE_NAME')  # Must have partition key: email (String)
ORDERS_TABLE_NAME = os.getenv('ORDERS_TABLE_NAME')  # Must have partition key: order_id (String)

# Email Config
ENABLE_EMAIL = os.getenv('ENABLE_EMAIL', 'False').lower() == 'true'
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
SENDER_EMAIL = os.getenv('SENDER_EMAIL')
SENDER_PASSWORD = os.getenv('SENDER_PASSWORD')

# SNS Config
ENABLE_SNS = os.getenv('ENABLE_SNS', 'False').lower() == 'true'
SNS_TOPIC_ARN = os.getenv('SNS_TOPIC_ARN')

# AWS Resources
dynamodb = boto3.resource('dynamodb', region_name=REGION)
users_table = dynamodb.Table(USERS_TABLE_NAME)
orders_table = dynamodb.Table(ORDERS_TABLE_NAME)
sns_client = boto3.client('sns', region_name=REGION)

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Dummy Product Data
products = {
    'veg': [
        {'name': 'Mango Pickle', 'price': 150, 'weight': '500g', 'image': 'veg_pickles/mango.jpg', 'stock': True},
        {'name': 'Lemon Pickle', 'price': 120, 'weight': '500g', 'image': 'veg_pickles/lemon.jpg', 'stock': False},
    ],
    'nonveg': [
        {'name': 'Chicken Pickle', 'price': 300, 'weight': '500g', 'image': 'non_veg_pickles/chicken.jpg', 'stock': True},
        {'name': 'Fish Pickle', 'price': 250, 'weight': '500g', 'image': 'non_veg_pickles/fish.jpg', 'stock': True},
    ],
    'snacks': [
        {'name': 'Banana Chips', 'price': 180, 'weight': '250g', 'image': 'snacks/banana_chips.jpg', 'stock': True},
        {'name': 'Chekkalu', 'price': 160, 'weight': '250g', 'image': 'snacks/chekkalu.jpg', 'stock': False},
    ]
}

# Helper Functions
def send_email(to_email, subject, body):
    if not ENABLE_EMAIL:
        logger.info(f"[Email Skipped] To: {to_email}, Subject: {subject}")
        return
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, to_email, msg.as_string())
        server.quit()
        logger.info(f"Email sent to {to_email}")
    except Exception as e:
        logger.error(f"Email sending failed: {e}")

def publish_to_sns(message, subject="New Order"):
    if not ENABLE_SNS or not SNS_TOPIC_ARN:
        logger.info("[SNS Skipped]")
        return
    try:
        sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Message=message,
            Subject=subject
        )
        logger.info("SNS notification sent.")
    except Exception as e:
        logger.error(f"SNS publish failed: {e}")

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])

        # DynamoDB Users table: Partition Key = email (String)
        existing = users_table.get_item(Key={'email': email})
        if 'Item' in existing:
            return render_template('signup.html', error="User already exists")

        users_table.put_item(Item={
            'email': email,
            'username': username,
            'password': password
        })
        logger.info(f"New user signed up: {email}")
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        user = users_table.get_item(Key={'email': email}).get('Item')
        if not user or not check_password_hash(user['password'], password):
            return render_template('login.html', error="Invalid credentials")

        session['user'] = email
        session['cart'] = []
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/veg_pickles')
def veg_pickles():
    return render_template('veg_pickles.html', products=products['veg'])

@app.route('/nonveg_pickles')
def nonveg_pickles():
    return render_template('nonveg_pickles.html', products=products['nonveg'])

@app.route('/snacks')
def snacks():
    return render_template('snacks.html', products=products['snacks'])

@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    if 'cart' not in session:
        session['cart'] = []

    name = request.form['product_name']
    price = int(request.form['price'])
    quantity = int(request.form['quantity'])

    session['cart'].append({'name': name, 'price': price, 'quantity': quantity})
    session.modified = True
    return redirect(url_for('cart'))

@app.route('/cart')
def cart():
    cart = session.get('cart', [])
    total = sum(item['price'] * item['quantity'] for item in cart)
    return render_template('cart.html', cart=cart, total=total)

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        phone = request.form['phone']
        address = request.form['address']
        cart = session.get('cart', [])

        if not cart:
            return redirect(url_for('cart'))

        order_id = str(uuid.uuid4())  # Used as Partition Key for Orders table
        orders_table.put_item(Item={
            'order_id': order_id,
            'user_email': session['user'],
            'items': cart,
            'name': name,
            'email': email,
            'phone': phone,
            'address': address
        })

        message = f"New Order from {name} ({email})\nOrder ID: {order_id}\nItems: {json.dumps(cart)}"
        publish_to_sns(message)
        send_email(email, "Order Confirmation", f"Thank you for your order!\n\n{message}")

        session['cart'] = []
        return redirect(url_for('success'))
    return render_template('checkout.html')

@app.route('/success')
def success():
    return render_template('success.html')

# Run the application
if _name_ == '_main_':
    app.run(debug=True, host='0.0.0.0', port=5000)
