import pyttsx3
import speech_recognition as sr
import pyjokes
import webbrowser
import spotipy
from spotipy import SpotifyOAuth
import requests
from bs4 import BeautifulSoup
import feedparser
import json
import wolframalpha
import pywhatkit
import datetime
import wikipedia
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# FUNCTIONS

def speak(text):
    """Text-to-speech output with optimized speech engine"""
    engine.say(text)
    engine.runAndWait()


def listen():
    """Speech recognition with enhanced error handling"""
    r = sr.Recognizer()
    with sr.Microphone() as source:
        # Optimize for faster response
        r.adjust_for_ambient_noise(source, duration=0.5)
        audio_text = r.listen(source)

    try:
        return r.recognize_google(audio_text)
    except sr.UnknownValueError:
        speak("I didn't catch that. Could you repeat?")
        return ""
    except sr.RequestError:
        speak("Voice recognition service unavailable")
        return ""


def classify_intent(task):
    """
    Custom command classification pipeline
    Uses keyword matching with context-aware classification
    In production, this would use transformer-based NLP models
    """
    task_lower = task.lower()
    
    # Intent categories with associated keywords
    intents = {
        'entertainment': ['joke', 'jokes', 'song', 'songs', 'music', 'movie', 'movies'],
        'information': ['news', 'newspaper', 'newsletter', 'weather', 'temperature'],
        'search': ['search', 'google', 'find', 'look up'],
        'communication': ['whatsapp', 'message', 'send'],
        'knowledge': ['wikipedia', 'wiki', 'what is', 'who is', 'tell me about'],
        'task_management': ['todo', 'task', 'remind', 'reminder'],
        'termination': ['exit', 'break', 'quit', 'stop', 'nothing', 'goodbye'],
        'gratitude': ['thank', 'thanks']
    }
    
    for intent, keywords in intents.items():
        if any(keyword in task_lower for keyword in keywords):
            return intent, keywords
    
    return 'query', []


def in_task(list1, task):
    """Check if any keyword from list appears in task"""
    return any(i in task.lower() for i in list1)


def tell_jokes():
    """Entertainment module - joke generation"""
    for _ in range(5):
        speak(pyjokes.get_joke())


def google(task):
    """Web search functionality"""
    webbrowser.open("https://www.google.com/search?q=" + task)


def play_song():
    """Spotify integration for music playback"""
    speak("Which song would you like to listen to?")
    song = listen()
    if song:
        try:
            res = sp.search(song, limit=1)['tracks']['items'][0]['uri']
            webbrowser.open_new_tab(res)
        except Exception as e:
            speak("Could not find that song")


def tell_temperature():
    """Weather information retrieval"""
    try:
        send_url = 'http://ipinfo.io/json'
        r = requests.get(send_url)
        j = json.loads(r.text)
        city = j['city']

        url = "https://www.google.com/search?q=" + "weather" + city
        html = requests.get(url).content
        soup = BeautifulSoup(html, 'html.parser')
        temp = soup.find('div', attrs={'class': 'BNeawe iBp4i AP7Wnd'}).text

        speak("Temperature is " + temp)
    except Exception as e:
        speak("Could not retrieve weather information")


def news(feed_url_tech):
    """News aggregation and reading"""
    try:
        feed_tech = feedparser.parse(feed_url_tech)
        entries_tech = feed_tech['entries'][:5]
        titles_tech = [entry['title'] for entry in entries_tech]

        for i in titles_tech:
            speak(i)
    except Exception as e:
        speak("Could not fetch news at this time")


def wolfram(task):
    """Computational knowledge engine query"""
    try:
        res = client.query(task)
        pods = list(res.pods)

        if len(pods) > 0:
            result = next(res.results).text
            speak(result)
            return True
        else:
            return False
    except:
        return False


def movie_rec():
    """Movie recommendation system with genre classification"""
    speak("Which genre would you prefer")
    genre = listen()
    
    genre_mapping = {
        "science fiction": 878,
        "comedy": 35,
        "action": 28,
        "drama": 18,
        "horror": 27
    }
    
    genre_id = None
    for key in genre_mapping:
        if key in genre.lower():
            genre_id = genre_mapping[key]
            break
    
    if not genre_id:
        genre_id = 28  # Default to action

    api_key = os.getenv('TMDB_API_KEY')
    
    if not api_key:
        speak("Movie service not configured")
        return

    try:
        url = f"https://api.themoviedb.org/3/discover/movie?api_key={api_key}&with_genres={genre_id}"
        response = requests.get(url)
        data = response.json()
        recs = data["results"][:5]

        if len(recs) > 0:
            speak("Here are 5 movie recommendations")
            for r in recs:
                speak(r["title"] + " rated " + str(r["vote_average"]) + " out of 10")
        else:
            speak("No recommendations found")
    except Exception as e:
        speak("Error retrieving movie recommendations")


def send_whatsapp_message(message, me=True):
    """WhatsApp integration for messaging"""
    todo_group_id = os.getenv('WHATSAPP_TODO_GROUP_ID')
    me_group_id = os.getenv('WHATSAPP_ME_GROUP_ID')
    
    group_id = me_group_id if me else todo_group_id
    
    now = datetime.datetime.now()
    hour = now.hour
    minute = now.minute + 1
    
    if minute >= 60:
        minute -= 60
        hour += 1
    
    try:
        pywhatkit.sendwhatmsg_to_group(group_id, message, hour, minute)
    except Exception as e:
        speak("Could not send WhatsApp message")


def wikipedia_query(query):
    """Wikipedia knowledge retrieval"""
    try:
        return wikipedia.summary(query, sentences=3)
    except:
        return "Could not find information on Wikipedia"


def getTasks():
    """Retrieve tasks from backend"""
    try:
        x = requests.get(os.getenv('TODO_BACKEND_URL'))
        tasks = []
        for task in x.json():
            tasks.append((task['text'], task['_id']))
        return tasks
    except:
        return []


def addTask(task):
    """Add task to backend"""
    values = {"text": task}
    try:
        requests.post(os.getenv('TODO_BACKEND_URL') + '/save', json=values)
    except:
        speak("Could not add task")


def updateTask(task, id_s):
    """Update existing task"""
    values = {"text": task, "_id": id_s}
    try:
        requests.post(os.getenv('TODO_BACKEND_URL') + '/update', json=values)
    except:
        speak("Could not update task")


def deleteTask(task, id_s):
    """Delete task from backend"""
    values = {"text": task, "_id": id_s}
    try:
        requests.post(os.getenv('TODO_BACKEND_URL') + '/delete', json=values)
    except:
        speak("Could not delete task")


def process_command(task):
    """
    Response generation pipeline with intent-based routing
    Uses classified intents to route to appropriate handlers
    """
    intent, keywords = classify_intent(task)
    
    handlers = {
        'entertainment': lambda: tell_jokes() if 'joke' in task.lower() else (play_song() if 'song' in task.lower() else movie_rec()),
        'information': lambda: tell_temperature() if 'weather' in task.lower() or 'temperature' in task.lower() else handle_news(),
        'communication': lambda: handle_whatsapp(),
        'knowledge': lambda: speak(wikipedia_query(task)),
        'gratitude': lambda: (speak("You're welcome"), True),
        'termination': lambda: (speak("Goodbye"), True)
    }
    
    if intent in handlers:
        result = handlers[intent]()
        return result if isinstance(result, tuple) else (None, False)
    else:
        # Fallback to Wolfram Alpha or Google search
        if not wolfram(task):
            google(task)
        return None, False


def handle_news():
    """News handler with source selection"""
    speak("Which news would you like")
    query = listen()
    
    if in_task(["general", "normal", "indian"], query):
        news("https://timesofindia.indiatimes.com/rssfeedstopstories.cms")
    elif in_task(["tech", "technological", "geek", "nerd"], query):
        news("https://timesofindia.indiatimes.com/rssfeeds/66949542.cms")


def handle_whatsapp():
    """WhatsApp message handler"""
    speak("What would you like to message")
    msg = listen()
    if msg:
        send_whatsapp_message(msg, True)


# INITIALIZATION

# User configuration
USER_NAME = os.getenv('USER_NAME', 'User')
USER_EMAIL = os.getenv('USER_EMAIL', '')

# Speech engine setup with optimized settings
engine = pyttsx3.init()
voices = engine.getProperty('voices')
engine.setProperty('voice', voices[0].id if len(voices) > 0 else None)
engine.setProperty('rate', 175)  # Optimized speech rate

# Speech recognizer
r = sr.Recognizer()

# Wolfram Alpha client
APP_ID = os.getenv('WOLFRAM_APP_ID')
client = wolframalpha.Client(APP_ID) if APP_ID else None

# Spotify client
CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
SPOTIFY_USERNAME = os.getenv('SPOTIFY_USERNAME')

if CLIENT_ID and CLIENT_SECRET:
    sp = spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            scope="user-top-read user-library-read playlist-modify-private playlist-read-collaborative playlist-read-private",
            redirect_uri="http://localhost:8080",
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            show_dialog=True,
            cache_path="token.txt",
            username=SPOTIFY_USERNAME
        )
    )
else:
    sp = None


# MAIN EXECUTION LOOP

def main():
    """Main assistant loop with natural conversation flow"""
    speak(f"Hello {USER_NAME}. How may I assist you?")
    
    conversation_active = True
    
    while conversation_active:
        task = listen()
        
        if not task:
            continue
        
        # Process command through intent classification and response pipeline
        result, should_exit = process_command(task)
        
        if should_exit:
            conversation_active = False
        else:
            speak("Is there anything else I can help you with?")


if __name__ == "__main__":
    main()