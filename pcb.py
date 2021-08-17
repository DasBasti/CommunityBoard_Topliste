from flask import Flask, request, render_template, session, redirect, request, url_for
from flask.helpers import make_response
from flask_dance.contrib.twitch import make_twitch_blueprint, twitch

from flask_sqlalchemy import SQLAlchemy
import json, os

from sqlalchemy import and_
from sqlalchemy.orm import relationship
from sqlalchemy.sql.expression import select
from sqlalchemy.sql.functions import user
from dotenv import load_dotenv
from pprint import PrettyPrinter

load_dotenv()  # take environment variables from .env.

import logging
#FORMAT = '%(asctime)s - %(module)s - %(levelname)s - Thread_name: %(threadName)s - %(message)s'
FORMAT = '%(message)s'
logging.basicConfig(
    format=FORMAT, datefmt='%m/%d/%Y %I:%M:%S %p',
    filename='app.log', level=logging.INFO)
logger = logging.getLogger('sqlalchemy.engine')
logger.setLevel(logging.INFO)

pp = PrettyPrinter()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://{user}:{pwd}@localhost/pcb?charset=utf8mb4'.format(user=os.getenv("MYSQL_USER"), pwd=os.getenv("MYSQL_PWD"))
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['APPLICATION_ROOT'] = "/pcb"
app.config['SECRET_KEY'] = os.getenv("APP_SECRET_KEY") 

### REMOVE ON SERVER!
#os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

scope = [
        "user:read:subscriptions",
        "channel:read:subscriptions",
        "chat:edit",
        "chat:read",
    ]
blueprint = make_twitch_blueprint(
    client_id=os.getenv("TWITCH_CLIENTID"),
    client_secret=os.getenv("TWITCH_CLIENTSECRET"),
    scope=scope,
    redirect_to="index",
)
app.register_blueprint(blueprint, url_prefix="/login")

db = SQLAlchemy(app)

class pcb_string(db.Model):
    id = db.Column(db.Integer, primary_key = True)
    username = db.Column(db.String(100))
    str = db.Column(db.String(64), unique=True)
    counter = db.Column(db.Integer)
    upvotes = db.Column(db.Integer)
    last_seen = db.Column(db.TIMESTAMP, server_default=db.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"))
    hidden = db.Column(db.Boolean, default=False)
    name = db.Column(db.String(100), unique=True)
    voted = relationship('vote')

    def __init__(self, username, str):
        self.username = username
        self.str = str
        self.counter = 0
        self.upvotes = 0

class vote(db.Model):
    id = db.Column(db.Integer, primary_key = True)
    username = db.Column(db.String(100), index = True)
    str_id = db.Column(db.Integer, db.ForeignKey('pcb_string.id'))
    vote =  db.Column(db.Boolean, default=0)

def list_page(entries, pageusername="", template="main.html"):    
    if twitch.authorized and not session.get('user'):
        resp=twitch.get("users")
        print(resp.content)
        data = json.loads(resp.content)
        if "data" in data:
            session['user'] = data['data']
    username = ""
    if session.get('user'):
        username = session.get('user')[0]['display_name']
    return render_template(template, 
        entries = entries, 
        twitch=twitch.access_token,
        user=username,
        username=pageusername
    )
@app.route('/')
def index():
    username = ""
    if session.get('user'):
        username = session.get('user')[0]['display_name']
        subquery = select(vote.vote).where(and_(vote.str_id == pcb_string.id, vote.username==username)).correlate(pcb_string).label("voted")
        q=(db.session.query(pcb_string, subquery)
            .order_by(pcb_string.upvotes.desc(), pcb_string.counter.desc(), pcb_string.last_seen.desc())
        )
        return list_page(q.all())
    
    res = (pcb_string.query
        .order_by(pcb_string.upvotes.desc(), pcb_string.counter.desc(), pcb_string.last_seen.desc())
        .all())
    nl = []
    for t in res:
        nl.append({"pcb_string": t, "vote": None})
    return list_page(nl)

@app.route('/u/<username>')
def show_users_list(username):
    return list_page([ {"pcb_string": s, "vote": None} for s in pcb_string.query.filter(pcb_string.username.ilike(username)).order_by(pcb_string.last_seen.desc()).all()], username )

@app.route('/most')
def show_most_used():
    return list_page([ {"pcb_string": s, "vote": None} for s in pcb_string.query.filter().order_by(pcb_string.counter.desc()).all() ])

@app.route('/login')
def login():
    login_url = url_for('twitch.login')
    print(login_url)
    return redirect(login_url)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

def do_upvote(code):
    if session['user']:
        data = pcb_string.query.filter_by(str=code).first()
        if data:
            username = session.get('user')[0]['display_name']
            user_voted = vote.query.filter(
                and_(
                    vote.username == username,
                    vote.str_id == data.id,
                    )).first()
            if not user_voted:
                user_voted = vote(username=username, str_id=data.id, vote=0)
            if user_voted.vote == 0:
                data.upvotes +=1
                user_voted.vote = 1
                db.session.add(data)
                db.session.add(user_voted)
                db.session.commit()
            else:
                return "Vote not counted"
        else:
            return "String not found"
        return data.upvotes


@app.route('/up/<code>')
def upvote(code):
    do_upvote(code)
    if "url" in request.args:
        return redirect(request.args["url"])
    return redirect(url_for('index'))

@app.route('/api/up/<code>')
def api_upvote(code):
    votes = do_upvote(code)
    return make_response(str(votes), 200)


def do_downvote(code):
    if session['user']:
        data = pcb_string.query.filter_by(str=code).first()
        if data:
            username = session.get('user')[0]['display_name']
            user_voted = vote.query.filter(
                and_(
                    vote.username==username,
                    vote.str_id==data.id,
                    )).first()
            if not user_voted:
                user_voted = vote(username=username, str_id=data.id)
            if user_voted.vote == 1 and data.upvotes > 0:
                data.upvotes -=1
                user_voted.vote = 0
                db.session.add(data)
                db.session.add(user_voted)
                db.session.commit()
            else:
                return "Vote not counted"
        else:
            return "String not found"
        return data.upvotes

@app.route('/down/<code>')
def downvote(code):
    do_downvote(code)
    if "url" in request.args:
        return redirect(request.args["url"])
    return redirect(url_for('index'))

@app.route('/api/down/<code>')
def api_downvote(code):
    votes = do_downvote(code)
    return make_response(str(votes),200)

@app.route('/chat', methods=['POST'])
def chat_in():
    input = json.loads(request.data)
    if "message" in input and "username" in input:
        pcb_str = input['message'][:64]
        db_str = pcb_string.query.filter_by(str=pcb_str).first()
        if db_str == None:
            db_str = pcb_string(input['username'][:100], pcb_str)
        db_str.counter += 1 
        db.session.add(db_str)    
        db.session.commit()
    return ""

@app.route('/update_string', methods=['POST'])
def update_string():
    name = request.form.get('name')
    pcb_str = request.form.get('orig_pcb_string')
    db_str = pcb_string.query.filter_by(str=pcb_str).first()
    if db_str:
        db_str.name = name
        db_str.str = request.form.get('pcb_string')
        db.session.add(db_str)    
        db.session.commit()
    return redirect(url_for('index'))

@app.route('/api/alias/<alias>')
def get_from_alias(alias):
    str = pcb_string.query.filter_by(name=alias).first()
    if(str):
        return str.str
    else:
        return make_response("", 404)

@app.route('/delete_string', methods=['POST'])
def delete_string():
    pcb_str = request.form.get('orig_pcb_string')
    db_str = pcb_string.query.filter_by(str=pcb_str).first()
    if db_str and db_str.username == session.get('user')[0]['display_name']:
        db.session.delete(db_str)    
        db.session.commit()
    return redirect(url_for('index'))


if __name__ == '__main__':
    db.create_all()
    app.run(host="0.0.0.0", debug = True)