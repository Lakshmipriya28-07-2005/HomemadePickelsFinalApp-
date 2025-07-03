from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
import boto3
import uuid
import os
from dotenv import load_dotenv
import json


load_dotenv()

# App Initialization
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'secret')

# AWS Config
REGION = os.getenv('AWS_REGION_NAME', 'us-east-1')

# DynamoDB Setup
dynamodb = boto3.resource('dynamodb', region_name=REGION)
users_table = dynamodb.Table(os.getenv('USERS_TABLE_NAME'))
orders_table = dynamodb.Table(os.getenv('ORDERS_TABLE_NAME'))

# SNS Setup
ENABLE_SNS = os.getenv('ENABLE_SNS', 'False').lower() == 'true'
sns_topic_arn = os.getenv('SNS_TOPIC_ARN')
sns_client = boto3.client('sns', region_name=REGION)

# Dummy product data
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


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])

        existing = users_table.get_item(Key={'email': email})
        if 'Item' in existing:
            return render_template('signup.html', error="User already exists")

        users_table.put_item(Item={
            'email': email,
            'username': username,
            'password': password
        })
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

        # Save to DynamoDB
        order_id = str(uuid.uuid4())
        orders_table.put_item(Item={
            'order_id': order_id,
            'user_email': session['user'],
            'items': cart,
            'name': name,
            'email': email,
            'phone': phone,
            'address': address
        })

        # Optional SNS Notification
        if ENABLE_SNS and sns_topic_arn:
            message = f"New Order from {name} ({email})\nOrder ID: {order_id}\nItems: {json.dumps(cart)}"
            sns_client.publish(
                TopicArn=sns_topic_arn,
                Message=message,
                Subject="New Order Received"
            )

        session['cart'] = []
        return redirect(url_for('success'))

    return render_template('checkout.html')

@app.route('/success')
def success():
    return render_template('success.html')

if __name__ == '__main__':
    app.run(debug=True)
