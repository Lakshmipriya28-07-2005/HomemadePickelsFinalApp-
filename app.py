from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import boto3
import os
import uuid
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key')

USE_AWS = os.getenv('USE_AWS', 'False').lower() == 'true'
AWS_REGION_NAME = os.getenv('AWS_REGION_NAME', 'us-east-1')
USERS_TABLE = os.getenv('USERS_TABLE', 'Users')
ORDERS_TABLE = os.getenv('ORDERS_TABLE', 'Orders')

users = {}
orders = []

if USE_AWS:
    dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION_NAME)
    users_table = dynamodb.Table(USERS_TABLE)
    orders_table = dynamodb.Table(ORDERS_TABLE)

products = {
    1: {'name': 'Mango Pickle', 'price': 150, 'image': 'https://images.unsplash.com/photo-1586201375761-83865001e31c?w=300&h=200&fit=crop', 'description': 'Traditional spicy mango pickle'},
    2: {'name': 'Lemon Pickle', 'price': 120, 'image': 'https://images.unsplash.com/photo-1578662996442-48f60103fc96?w=300&h=200&fit=crop', 'description': 'Tangy lemon pickle'},
    3: {'name': 'Mixed Vegetable Pickle', 'price': 180, 'image': 'https://images.unsplash.com/photo-1571197110022-14f4e85f4c4c?w=300&h=200&fit=crop', 'description': 'Mixed vegetable pickle'},
    4: {'name': 'Garlic Pickle', 'price': 140, 'image': 'https://images.unsplash.com/photo-1599909533607-e1d1e2e2e3f4?w=300&h=200&fit=crop', 'description': 'Spicy garlic pickle'},
    5: {'name': 'Banana Chips', 'price': 80, 'image': 'https://images.unsplash.com/photo-1580873435531-d13f5d2e7c5d?w=300&h=200&fit=crop', 'description': 'Crispy banana chips'},
    6: {'name': 'Murukku', 'price': 100, 'image': 'https://images.unsplash.com/photo-1555681618-85c59b645fdc?w=300&h=200&fit=crop', 'description': 'Traditional murukku'},
    7: {'name': 'Tamarind Pickle', 'price': 160, 'image': 'https://images.unsplash.com/photo-1584277261846-c6a1672ed2d4?w=300&h=200&fit=crop', 'description': 'Tamarind pickle'},
    8: {'name': 'Coconut Chutney Powder', 'price': 90, 'image': 'https://images.unsplash.com/photo-1580635180657-5d6b6d3b0c27?w=300&h=200&fit=crop', 'description': 'Chutney powder'}
}

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/auth')
def auth():
    return render_template('auth.html')

@app.route('/register', methods=['POST'])
def register():
    username = request.form['username'].strip()
    email = request.form['email']
    password = request.form['password']

    if USE_AWS:
        try:
            response = users_table.get_item(Key={'username': username})
            if 'Item' in response:
                flash('Username already exists!')
                return redirect(url_for('auth'))
            users_table.put_item(Item={
                'username': username,
                'email': email,
                'password': generate_password_hash(password)
            })
        except Exception as e:
            flash('Error with AWS: ' + str(e))
            return redirect(url_for('auth'))
    else:
        if username in users:
            flash('Username already exists!')
            return redirect(url_for('auth'))
        users[username] = {
            'email': email,
            'password': generate_password_hash(password),
            'orders': []
        }

    session['username'] = username
    flash('Registration successful!')
    return redirect(url_for('show_products'))

@app.route('/login', methods=['POST'])
def login():
    username = request.form['username'].strip()
    password = request.form['password']

    user_data = None
    if USE_AWS:
        response = users_table.get_item(Key={'username': username})
        user_data = response.get('Item')
    else:
        user_data = users.get(username)

    if user_data and check_password_hash(user_data['password'], password):
        session['username'] = username
        return redirect(url_for('show_products'))

    flash('Invalid username or password!')
    return redirect(url_for('auth'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/products')
def show_products():
    if 'username' not in session:
        return redirect(url_for('auth'))
    return render_template('products.html', products=products)

@app.route('/add_to_cart/<int:product_id>')
def add_to_cart(product_id):
    if 'username' not in session:
        return redirect(url_for('auth'))

    cart = session.get('cart', {})
    cart[str(product_id)] = cart.get(str(product_id), 0) + 1
    session['cart'] = cart

    flash(f'{products[product_id]["name"]} added to cart!')
    return redirect(url_for('show_products'))

@app.route('/cart')
def cart():
    if 'username' not in session:
        return redirect(url_for('auth'))

    cart = session.get('cart', {})
    cart_items = []
    total = 0

    for pid, qty in cart.items():
        product = products[int(pid)]
        subtotal = product['price'] * qty
        cart_items.append({
            'id': pid,
            'name': product['name'],
            'price': product['price'],
            'quantity': qty,
            'subtotal': subtotal
        })
        total += subtotal

    return render_template('cart.html', cart_items=cart_items, total=total, products=products)

@app.route('/remove_from_cart/<int:product_id>')
def remove_from_cart(product_id):
    cart = session.get('cart', {})
    cart.pop(str(product_id), None)
    session['cart'] = cart
    flash('Item removed from cart!')
    return redirect(url_for('cart'))

@app.route('/checkout')
def checkout():
    if 'username' not in session:
        return redirect(url_for('auth'))

    cart = session.get('cart', {})
    if not cart:
        flash('Your cart is empty!')
        return redirect(url_for('show_products'))

    total = sum(products[int(pid)]['price'] * qty for pid, qty in cart.items())
    cart_items = [
        {
            'id': pid,
            'name': products[int(pid)]['name'],
            'quantity': qty,
            'subtotal': products[int(pid)]['price'] * qty
        } for pid, qty in cart.items()
    ]
    return render_template('checkout.html', total=total, cart_items=cart_items, products=products)

@app.route('/place_order', methods=['POST'])
def place_order():
    if 'username' not in session:
        return redirect(url_for('auth'))

    cart = session.get('cart', {})
    username = session['username']

    customer_details = {
        'first_name': request.form.get('firstName'),
        'last_name': request.form.get('lastName'),
        'email': request.form.get('email'),
        'phone': request.form.get('phone'),
        'address': request.form.get('address'),
        'city': request.form.get('city'),
        'state': request.form.get('state'),
        'pincode': request.form.get('pincode'),
        'notes': request.form.get('orderNotes'),
        'payment_method': request.form.get('paymentMethod')
    }

    order = {
        'id': str(uuid.uuid4()),
        'username': username,
        'items': cart.copy(),
        'customer_details': customer_details,
        'total': sum(products[int(pid)]['price'] * qty for pid, qty in cart.items()),
        'date': datetime.now().strftime('%B %d, %Y'),
        'status': 'confirmed'
    }

    if USE_AWS:
        try:
            orders_table.put_item(Item={
                'order_id': order['id'],
                'username': username,
                'order_data': order
            })
        except Exception as e:
            flash('AWS Order Save Error: ' + str(e))
            return redirect(url_for('checkout'))
    else:
        orders.append(order)
        if username in users:
            users[username]['orders'].append(order['id'])

    session['cart'] = {}
    return render_template('order_confirmation.html', order=order)


# ✅ Your required ending
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
