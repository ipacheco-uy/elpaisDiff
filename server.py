from flask import Flask
from nytdiff import main

app = Flask(__name__)


@app.route('/')
def hello_world():
    return 'Hello, News!'


@app.route('/check')
def check_news():
    main()
    return "Parsed!"
