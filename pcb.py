from operator import index
from flask import Flask, request, render_template, session, redirect, request, url_for, jsonify
from flask.helpers import make_response
from flask_dance.contrib.twitch import make_twitch_blueprint, twitch

from flask_sqlalchemy import SQLAlchemy
import json, os

from sqlalchemy import and_, or_
from sqlalchemy.orm import relationship
from sqlalchemy.sql.expression import select
from sqlalchemy.sql.functions import char_length, user
from dotenv import load_dotenv
from pprint import PrettyPrinter

from sqlalchemy.sql.schema import ForeignKey

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
    fav = relationship('fav')

    def __init__(self, username, str):
        self.username = username
        self.str = str
        self.counter = 0
        self.upvotes = 0
    
    def toJson(self):
        datestr = None
        if self.last_seen: 
            datestr = self.last_seen.strftime('%Y-%m-%d %H:%M:%S') 
        return {
        "id": self.id,
        "username": self.username,
        "str": self.str,
        "counter": self.counter,
        "upvotes": self.upvotes,
        "last_seen": datestr,
        "name": self.name,
        "voted": self.voted,
        "fav": self.fav.id,
        }
class vote(db.Model):
    id = db.Column(db.Integer, primary_key = True)
    username = db.Column(db.String(100), index = True)
    str_id = db.Column(db.Integer, db.ForeignKey('pcb_string.id'))
    vote =  db.Column(db.Boolean, default=0)

    def toJson(self):
        return {
            "id": self.id,
            "username": self.username,
            "str_id": self.str_id,
            "vote": self.vote,
        }

class fav(db.Model):
    id = db.Column(db.Integer, primary_key = True)
    username = db.Column(db.String(100), index = True)
    str_id = db.Column(db.Integer, db.ForeignKey('pcb_string.id'))

    def toJson(self):
        return {
            "id": self.id,
            "username": self.username,
            "str_id": self.str_id
        }

class led(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner = db.Column(db.String(100), index = True, unique=True)
    color = db.Column(db.Integer)
    animation = db.Column(db.String(100))
    last_seen = db.Column(db.TIMESTAMP, server_default=db.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"))

    def toJson(self):
        datestr = None
        if self.last_seen: 
            datestr = self.last_seen.strftime('%Y-%m-%d %H:%M:%S') 
        return {
        "id": self.id,
        "owner": self.owner,
        "color": self.color,
        "animation": self.animation,
        "last_seen": datestr
        }


class board(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), index = True, unique=True)
    owner = db.Column(db.String(100), index = True)
    state = db.Column(db.String(6), index = True)
    last_seen = db.Column(db.TIMESTAMP, server_default=db.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"))

    def toJson(self):
        datestr = None
        if self.last_seen: 
            datestr = self.last_seen.strftime('%Y-%m-%d %H:%M:%S') 
        return {
        "id": self.id,
        "owner": self.owner,
        "last_seen": datestr
        }

def list_page(entries, pageusername="", template="main.html"):    
    if twitch.authorized and not session.get('user'):
        resp=twitch.get("users")
        data = json.loads(resp.content)
        if "data" in data:
            session['user'] = data['data']
    username = ""
    if session.get('user'):
        username = session.get('user')[0]['display_name']
    return render_template(template, 
        entries = entries, 
        twitch = twitch.access_token,
        user = username,
        username = pageusername,
        boards_online = boards_online()
    )

def boards_online():
    all_boards = board.query.filter_by(state="online").all()
    res = []
    for this_board in all_boards:
        res.append({"board":this_board.name})
    
    return {"count":len(all_boards),"list":res}


@app.route('/')
def index():
    username = ""
    if session.get('user'):
        username = session.get('user')[0]['display_name']
        subquery = select(vote.vote).where(and_(vote.str_id == pcb_string.id, vote.username==username)).correlate(pcb_string).label("voted")
        q=(db.session.query(pcb_string, subquery, fav).join(fav, and_(fav.username==username, fav.str_id==pcb_string.id), isouter=True)
            .order_by(pcb_string.upvotes.desc(), pcb_string.counter.desc(), pcb_string.last_seen.desc())
        )
        return list_page(q.all())
    
    res = (pcb_string.query
        .order_by(pcb_string.upvotes.desc(), pcb_string.counter.desc(), pcb_string.last_seen.desc())
        .all())
    nl = []
    for t in res:
        nl.append({"pcb_string": t, "vote": None, "fav": None})
    return list_page(nl)

@app.route('/u/<username>')
def show_users_list(username):
    user = ""
    if session.get('user'):
        user = session.get('user')[0]['display_name']
        return list_page(db.session.query(pcb_string, fav)
            .filter(pcb_string.username.ilike(username))
            .join(fav, and_(fav.username==user, fav.str_id==pcb_string.id), isouter=True)
            .order_by(pcb_string.last_seen.desc())
            .all(), username )
    
    return list_page([ {"pcb_string": s, "vote": None, "fav": None} for s in pcb_string.query.filter(pcb_string.username.ilike(username)).order_by(pcb_string.last_seen.desc()).all()], username )

@app.route('/u/<username>/fav')
def show_users_favorites(username):
    user = ""
    if session.get('user'):
        user = session.get('user')[0]['display_name']
        return list_page(db.session.query(pcb_string, fav)
            .filter(fav.id != None)
            .join(fav, and_(fav.username==user, fav.str_id==pcb_string.id), isouter=True)
            .order_by(pcb_string.last_seen.desc())
            .all(), username )

    return list_page([ {"pcb_string": s, "vote": None, "fav": None} for s in fav.query.filter(fav.username.ilike(username))
        .join(pcb_string, pcb_string.id == fav.str_id)], username )
"""
@app.route('/most')
def show_most_used():
    return list_page([ {"pcb_string": s, "vote": None, "fav": None} for s in pcb_string.query.filter().order_by(pcb_string.counter.desc()).all() ])
"""
@app.route('/login')
def login():
    login_url = url_for('twitch.login')
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

@app.route('/api/boards/<string:board_id>/<string:status>')
def api_board_status(board_id, status):
    this_board = board.query.filter_by(name=board_id).first()
    if not this_board:
        this_board = board()
        this_board.name = board_id
    this_board.state = "off"
    if status == "online":
        this_board.state = "online"
    db.session.add(this_board)
    db.session.commit()
    return make_response("OK", 200)

@app.route('/api/boards')
def api_boards():    
    return jsonify(boards_online())

@app.route('/api/fav/<code>')
def api_fav(code):
    ret = "error"
    if session['user']:
        data = pcb_string.query.filter_by(str=code).first()
        if data:
            username = session.get('user')[0]['display_name']
            faved = fav.query.filter_by(username=username, str_id=data.id).first()
            if faved:
                db.session.delete(faved)
                ret = "dislike"
            else:
                faved = fav(username=username, str_id=data.id)
                db.session.add(faved)
                ret = "like"
            db.session.commit()
        else:
            return make_response("String not found", 404)

    return make_response(ret, 200)


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
    return redirect(request.referrer)

@app.route('/api/alias/<alias>')
def get_from_alias(alias):
    str = pcb_string.query.filter_by(name=alias).first()
    if(str):
        str.counter += 1
        db.session.add(str)
        db.session.commit()
        return str.str
    else:
        return make_response("", 404)

@app.route('/api/animation/<alias>')
def get_animation_frames(alias):
    str = pcb_string.query.filter(pcb_string.name.like(alias+"-%")).first()
    if(str):
        user = str.username
        anim_set = pcb_string.query.filter(pcb_string.username==user, pcb_string.name.ilike(alias+"-%")).order_by(pcb_string.name.asc()).all()
        return json.dumps([ k.str for k in anim_set ])
    else:
        return make_response("", 404)

@app.route('/delete_string', methods=['POST'])
def delete_string():
    pcb_str = request.form.get('orig_pcb_string')
    db_str = pcb_string.query.filter_by(str=pcb_str).first()
    if db_str and db_str.username == session.get('user')[0]['display_name']:
        db.session.delete(db_str)    
        db.session.commit()
    return redirect(request.referrer)

@app.route('/panel', methods=['GET'])
def read_whole_panel():
    panel = led.query.all()
    p = list()
    for l in panel:
        p.append(l.toJson())
    return make_response(jsonify(p))

@app.route('/panel/led/<id>', methods=['GET'])
def get_led_info(id):
    cur_led = led.query.filter(or_(led.id==id, led.owner==id)).first()
    if cur_led:
        return make_response(jsonify({"color":cur_led.color}))
    else:
        return make_response("not Found", 404)

@app.route('/panel/led/<id>', methods=['POST'])
def set_led_info(id):
    # nur mit masterpasswort wenn gesetzt
    if os.getenv("PANEL_SERVER_TOKEN") == request.form.get('auth'):
        owner = request.form.get("owner")
        cur_led = led.query.filter(or_(led.id==id, led.owner==id)).first()
        if(cur_led):
            if request.form.get("color"):
                cur_led.color = request.form.get("color")
            cur_led.animation = request.form.get("animation")
            db.session.add(cur_led)
            db.session.commit()
            return make_response("", 200)
        else:
            return make_response("User not Authorized", 401)    
    else:
        return make_response("Not Authorized", 401)

@app.route('/api/list')
def get_list_of_pcb_strings():
    if "page" in request.args:
        page = int(request.args["page"])
    else:
        page = 1
    if page < 1:
        page = 1
    if "num" in request.args:
        num = int(request.args["num"])
    else:
        num = 20
    start = (page-1)*num
    out = {"start": start, "elements": []}
    if "name" in request.args:
        namefilter = request.args["name"]
        total = pcb_string.query.filter(pcb_string.username==namefilter).count()
    else:
        namefilter = "%"
        total = pcb_string.query.count()
    username = None
    if session.get('user'):
        username = session.get('user')[0]['display_name']
        subquery = select(vote.vote).where(and_(vote.str_id == pcb_string.id, vote.username==username)).correlate(pcb_string).label("voted")
        q=(db.session.query(pcb_string, subquery, fav).join(fav, and_(fav.username==username, fav.str_id==pcb_string.id), isouter=True).filter(pcb_string.username.like(namefilter))
            .order_by(pcb_string.upvotes.desc(), pcb_string.counter.desc(), pcb_string.last_seen.desc()).offset(start).limit(num)
        )
        response =  make_response(render_template("list.json", entries=q.all(), username=username, total=total))
    else:
        res = (pcb_string.query.filter(pcb_string.username.like(namefilter))
            .order_by(pcb_string.upvotes.desc(), pcb_string.counter.desc(), pcb_string.last_seen.desc())
            .offset(start).limit(num))
        nl = []
        for t in res:
            nl.append({"pcb_string": t, "vote": None, "fav": None})
        response = make_response(render_template("list.json", entries=nl, total=total))

    response.headers['Content-Type'] = 'application/json'
    return response

#endpoint top update last_seen
if __name__ == '__main__':
    db.create_all()

    app.run(host="0.0.0.0", port=8888, debug = True)