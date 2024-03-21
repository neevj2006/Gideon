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


# FUCNTIONS
def speak(text):
    engine.say(text)
    engine.runAndWait()


def listen():
    r = sr.Recognizer()
    with sr.Microphone() as source:
        audio_text = r.listen(source)

    try:
        return r.recognize_google(audio_text)
    except:
        speak("Voice Recognition Failed")


def in_task(list1, task):
    for i in list1:
        if i in task:
            return True


def tell_jokes():
    for _ in range(5):
        speak(pyjokes.get_joke())


def google(task):
    webbrowser.open("https://www.google.com/search?q="+task)


def play_song():
    CLIENT_ID = "b890c23f87884958bff8b927ef2c879d"
    CLIENT_SECRET = "f553a526548a482ea8782782f8c6bbd4"

    # Spotify Authentication
    sp = spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            scope="user-top-read user-library-read playlist-modify-private playlist-read-collaborative playlist-read-private",
            redirect_uri="http://example.com",
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            show_dialog=True,
            cache_path="token.txt",
            username="3165do7y2lvhed6ax7o3guhrhq7m"
        )
    )
    speak("Which song would you like to listen to?")
    song = listen()
    res = sp.search(song, limit=1)['tracks']['items'][0]['uri']
    webbrowser.open(res)


def tell_temperature():
    send_url = 'http://ipinfo.io/json'
    r = requests.get(send_url)

    j = json.loads(r.text)

    city = j['city']

    # creating url and requests instance
    url = "https://www.google.com/search?q="+"weather"+city
    html = requests.get(url).content

    # getting raw data
    soup = BeautifulSoup(html, 'html.parser')
    temp = soup.find('div', attrs={'class': 'BNeawe iBp4i AP7Wnd'}).text

    # speaking all data
    speak("Temperature is " + temp)


def news(feed_url_tech):
    # Get the feed data
    feed_tech = feedparser.parse(feed_url_tech)

    # Extract the titles and links of the top 10 entries
    entries_tech = feed_tech['entries'][:5]
    titles_tech = [entry['title'] for entry in entries_tech]

    for i in titles_tech:
        speak(i)


def wolfram(task):
    res = client.query(task)
    pods = list(res.pods)

    if len(pods) > 0:
        result = next(res.results).text
        speak(result)
    else:
        return False


def movie_rec():
    speak("Which genre would you prefer")
    genre = listen()
    if in_task(["science", "sci-fi", "fiction"], genre):
        genre_id = 878
    elif in_task(["comedy"], genre):
        genre_id = 80
    elif in_task(["action"], genre):
        genre_id = 28

    api_key = "THE_MOVIE_DB_API_KEY"
    try:
        url = f"https://api.themoviedb.org/3/discover/movie?api_key={api_key}&with_genres={genre_id}"
    except:
        speak("Error occured")

    response = requests.get(url)
    data = response.json()

    recs = data["results"][:5]

    if len(recs) > 0:
        speak(f"Here are 5 movie recommendations")

        for r in recs:
            speak(r["title"] + " " + str(r["vote_average"]) + " " + "out of 10")

    else:
        speak("No recommendations found")


# MAIN CODE
# General
NAME = "Neev"
FULL_NAME = "Neev Jain"
EMAIL = "neev0511jain@gmail.com"

# Speaking
engine = pyttsx3.init()
voices = engine.getProperty('voices')
engine.setProperty('voice', voices[2].id)

# Listen
r = sr.Recognizer()

# Wolframalpha
APP_ID = "WOLFRAMALPHA_API_KEY"
client = wolframalpha.Client(APP_ID)

# MAIN

speak("Hello Mister Neev. How may I help you?")
flag = False
while True:
    if flag:
        speak("Would you like my assistance with anything else?")

    task = listen()
    if in_task(["joke", "jokes"], task):
        tell_jokes()

    elif in_task(["song", "songs"], task):
        play_song()

    elif in_task(["temperature", "weather"], task):
        tell_temperature()

    elif in_task(["news", "newspaper", "newsletter"], task):
        speak("Which news would you like")

        query = listen()

        if in_task(["general", "normal", "indian"], query):
            news("https://timesofindia.indiatimes.com/rssfeedstopstories.cms")
        elif in_task(["tech", "technological", "geek", "nerd"], query):
            news("https://timesofindia.indiatimes.com/rssfeeds/66949542.cms")

    elif in_task(["movie"], task):
        movie_rec()

    elif in_task(["thank"], task):
        speak("You're welcome")
        break

    elif in_task(["exit", "break", "quit", "stop", "nothing"], task):
        break

    else:
        x = wolfram(task)
        if x == False:
            google(task)
    flag = True
