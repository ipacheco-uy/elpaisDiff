from flask import Flask
from nytdiff import main
from decouple import config as config_decouple


def create_app(enviroment):
    app = Flask(__name__)

    app.config.from_object(enviroment)

    with app.app_context():
        db.init_app(app)
        db.create_all()

    return app


enviroment = config['development']
if config_decouple('PRODUCTION', default=False):
    enviroment = config['production']

app = create_app(enviroment)


@app.route('/')
def hello_world():
    return 'Hello, News!'


@app.route('/check')
def check_news():
    main()