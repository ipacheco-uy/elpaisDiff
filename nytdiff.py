#!/usr/bin/python3

import collections
import hashlib
import logging
import os
import sys
import time
from datetime import datetime

import bleach
import dataset
import feedparser
import tweepy
from PIL import Image
from pytz import timezone
from selenium import webdriver
from simplediff import html_diff

TIMEZONE = 'Europe/Brussels'
LOCAL_TZ = timezone(TIMEZONE)
MAX_RETRIES = 10
RETRY_DELAY = 3

if 'TESTING' in os.environ:
    if os.environ['TESTING'] == 'False':
        TESTING = False
    else:
        TESTING = True
else:
    TESTING = True

if 'LOG_FOLDER' in os.environ:
    LOG_FOLDER = os.environ['LOG_FOLDER']
else:
    LOG_FOLDER = ''


class BaseParser(object):
    def __init__(self, api):
        self.rss_sites = list()
        self.payload = None
        self.articles = dict()
        self.current_ids = set()
        self.filename = str()
        self.db = dataset.connect('sqlite:///titles.db')
        self.api = api

    def test_twitter(self):
        print(self.api.rate_limit_status())
        print(self.api.me().name)

    def remove_old(self, column='id'):
        db_ids = set()
        for nota_db in self.articles_table.find(status='home'):
            db_ids.add(nota_db[column])
        for to_remove in (db_ids - self.current_ids):
            if column == 'id':
                data = dict(id=to_remove, status='removed')
            else:
                data = dict(article_id=to_remove, status='removed')
            self.articles_table.update(data, [column])
            logging.info('Removed %s', to_remove)

    def get_prev_tweet(self, article_id, column):
        if column == 'id':
            search = self.articles_table.find_one(id=article_id)
        else:
            search = self.articles_table.find_one(article_id=article_id)
        if search is None:
            return None
        else:
            if 'tweet_id' in search:
                return search['tweet_id']
            else:
                return None

    def update_tweet_db(self, article_id, tweet_id, column):
        if column == 'id':
            article = {
                'id': article_id,
                'tweet_id': tweet_id
            }
        else:
            article = {
                'article_id': article_id,
                'tweet_id': tweet_id
            }
        self.articles_table.update(article, [column])
        logging.debug('Updated tweet ID in db')

    def media_upload(self, filename):
        if TESTING:
            return 1
        try:
            response = self.api.media_upload(filename)
        except:
            print (sys.exc_info()[0])
            logging.exception('Media upload')
            return False
        return response.media_id_string

    def tweet_with_media(self, text, images, reply_to=None):
        if TESTING:
            print (text, images, reply_to)
            return True
        try:
            if reply_to is not None:
                tweet_id = self.api.update_status(
                    status=text, media_ids=images,
                    in_reply_to_status_id=reply_to)
            else:
                tweet_id = self.api.update_status(
                    status=text, media_ids=images)
        except:
            logging.exception('Tweet with media failed')
            print (sys.exc_info()[0])
            return False
        return tweet_id

    def tweet_text(self, text):
        if TESTING:
            print (text)
            return True
        try:
            tweet_id = self.api.update_status(status=text)
        except:
            logging.exception('Tweet text failed')
            print (sys.exc_info()[0])
            return False
        return tweet_id

    def tweet(self, text, article_id, url, column='id'):
        images = list()
        image = self.media_upload('./output/' + self.filename + '.png')
        logging.info('Media ready with ids: %s', image)
        images.append(image)
        logging.info('Text to tweet: %s', text)
        logging.info('Article id: %s', article_id)
        reply_to = self.get_prev_tweet(article_id, column)
        if reply_to is None:
            logging.info('Tweeting url: %s', url)
            tweet = self.tweet_text(url)
            # if TESTING, give a random id based on time
            reply_to = tweet.id if not TESTING else time.time()
        logging.info('Replying to: %s', reply_to)
        tweet = self.tweet_with_media(text, images, reply_to)
        if TESTING :
            # if TESTING, give a random id based on time
            tweet_id = time.time()
        else:
            tweet_id = tweet.id
        logging.info('Id to store: %s', tweet_id)
        self.update_tweet_db(article_id, tweet_id, column)
        return

    def strip_html(self, html_str):
        """
        a wrapper for bleach.clean() that strips ALL tags from the input
        """
        tags = []
        attr = {}
        styles = []
        strip = True
        return bleach.clean(html_str,
                            tags=tags,
                            attributes=attr,
                            styles=styles,
                            strip=strip)

    def show_diff(self, old, new):
        if len(old) == 0 or len(new) == 0:
            logging.info('Old or New empty')
            return False
        new_hash = hashlib.sha224(new.encode('utf8')).hexdigest()
        logging.info(html_diff(old, new))
        html = """
        <!doctype html>
        <html lang="en">
          <head>
            <meta charset="utf-8">
            <link rel="stylesheet" href="./css/styles.css">
          </head>
          <body>
          <p>
          {}
          </p>
          </body>
        </html>
        """.format(html_diff(old, new))
        with open('tmp.html', 'w') as f:
            f.write(html)

        CHROMEDRIVER_PATH = os.environ.get('CHROMEDRIVER_PATH', '/usr/local/bin/chromedriver')
        driver = webdriver.Chrome(CHROMEDRIVER_PATH)
        driver.get('file://%s/tmp.html' % os.getcwd())
        e = driver.find_element_by_xpath('//p')
        start_height = e.location['y']
        block_height = e.size['height']
        end_height = start_height
        start_width = e.location['x']
        block_width = e.size['width']
        end_width = start_width
        total_height = start_height + block_height + end_height
        total_width = start_width + block_width + end_width
        timestamp = str(int(time.time()))
        driver.save_screenshot('./tmp.png')
        img = Image.open('./tmp.png')
        img2 = img.crop((0, 0, total_width, total_height))
        if int(total_width) > int(total_height * 2):
            background = Image.new('RGBA', (total_width, int(total_width / 2)),
                                   (255, 255, 255, 0))
            bg_w, bg_h = background.size
            offset = (int((bg_w - total_width) / 2),
                      int((bg_h - total_height) / 2))
        else:
            background = Image.new('RGBA', (total_width, total_height),
                                   (255, 255, 255, 0))
            bg_w, bg_h = background.size
            offset = (int((bg_w - total_width) / 2),
                      int((bg_h - total_height) / 2))
        background.paste(img2, offset)
        self.filename = timestamp + new_hash
        background.save('./output/' + self.filename + '.png')
        return True

    def __str__(self):
        return '\n'.join(self.rss_sites)


class RSSParser(BaseParser):
    def __init__(self, api, rss_sites):
        BaseParser.__init__(self, api)
        self.rss_sites = rss_sites
        self.articles_table = self.db['rss_ids']
        self.versions_table = self.db['rss_versions']

    def entry_to_dict(self, article):
        article_dict = dict()
        article_dict['article_id'] = article.id.split(' ')[0]
        article_dict['url'] = article.link
        article_dict['title'] = article.title
        article_dict['abstract'] = self.strip_html(article.description) if 'description'in article and \
                                                                           article.description is not None else ""
        article_dict['author'] = article.author if 'author' in article else ""
        od = collections.OrderedDict(sorted(article_dict.items()))
        article_dict['hash'] = hashlib.sha224(
            repr(od.items()).encode('utf-8')).hexdigest()
        article_dict['date_time'] = datetime.now(LOCAL_TZ)
        return article_dict

    def store_data(self, data, name, handler):
        if self.articles_table.find_one(article_id=data['article_id']) is None:  # New
            article = {
                'article_id': data['article_id'],
                'add_dt': data['date_time'],
                'status': 'home',
                'tweet_id': None
            }
            self.articles_table.insert(article)
            logging.info('New article tracked: %s', data['url'])
            data['version'] = 1
            self.versions_table.insert(data)
        else:
            # re insert
            if self.articles_table.find_one(article_id=data['article_id'], status='removed') is not None:
                article = {
                    'article_id': data['article_id'],
                    'add_dt': data['date_time'],
                }

            count = self.versions_table.count(self.versions_table.table.columns.article_id == data['article_id'],
                hash=data['hash'])
            if count == 1:  # Existing
                pass
            else:  # Changed
                result = self.db.query('SELECT * \
                                       FROM rss_versions\
                                       WHERE article_id = "%s" \
                                       ORDER BY version DESC \
                                       LIMIT 1' % (data['article_id']))
                for row in result:
                    data['version'] = row['version']
                    self.versions_table.insert(data)
                    url = data['url']
                    if row['url'] != data['url']:
                        if self.show_diff(row['url'], data['url']):
                            tweet_text = "Modificación de Url"
                            self.tweet(tweet_text, data['article_id'], url,
                                       'article_id')
                    if row['title'] != data['title']:
                        if self.show_diff(row['title'], data['title']):
                            tweet_text = "Modificación de Titulo @%s" % handler
                            self.tweet(tweet_text, data['article_id'], url,
                                       'article_id')
                    if row['abstract'] != data['abstract']:
                        if self.show_diff(row['abstract'], data['abstract']):
                            tweet_text = "Modificación de la Descripción @%s" % handler
                            self.tweet(tweet_text, data['article_id'], url,
                                       'article_id')
                    if row['author'] != data['author']:
                        if self.show_diff(row['author'], data['author']):
                            tweet_text = "Modificación del autor @%s" % handler
                            self.tweet(tweet_text, data['article_id'], url,
                                       'article_id')

    def loop_entries(self, entries, name, handler):
        if len(entries) == 0:
            return False
        for article in entries:
            try:
                article_dict = self.entry_to_dict(article)
                if article_dict is not None:
                    self.store_data(article_dict, name, handler)
                    self.current_ids.add(article_dict['article_id'])
            except BaseException as e:
                logging.exception('Problem looping RSS: %s', article)
                print ('Exception: {}'.format(str(e)))
                print('***************')
                print(article)
                print('***************')
                return False
        return True

    def parse_rss(self):
        for rss in self.rss_sites:
            logging.info('Parsing from %s', rss['name'])
            r = feedparser.parse(rss['url'])
            if r is None:
                logging.warning('Empty response RSS')
                return
            elif 'title' in r.feed:
                logging.info('Parsing %s', r.feed.title)
                loop = self.loop_entries(r.entries, rss['name'], rss['twitter'])
                if loop:
                    self.remove_old('article_id')
            else:
                logging.info('Skipping %s', r.feed)


def main():
    # logging
    logging.basicConfig(format='%(asctime)s %(name)13s %(levelname)8s: ' + '%(message)s', level=logging.INFO)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.info('Starting script')

    consumer_key = os.environ['TWITTER_CONSUMER_KEY']
    consumer_secret = os.environ['TWITTER_CONSUMER_SECRET']
    access_token = os.environ['TWITTER_ACCESS_TOKEN']
    access_token_secret = os.environ['TWITTER_ACCESS_TOKEN_SECRET']
    auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
    auth.secure = True
    auth.set_access_token(access_token, access_token_secret)
    twitter_api = tweepy.API(auth)
    logging.debug('Twitter API configured')

    try:
        logging.debug('Starting RSS')
        rss_sites = [
            {
                'url': 'https://www.elobservador.com.uy/rss/elobservador.xml',
                'name': 'El Observador',
                'twitter': 'ObservadorUY'
            },
            {
                'url': 'https://www.elpais.com.uy/rss/',
                'name': 'El Pais',
                'twitter': 'elpaisuy'
            },
            {
                'url': 'http://brecha.com.uy/feed/',
                'name': 'Brecha',
                'twitter': 'SemanarioBrecha'
            },
            {
                'url': 'https://www.montevideo.com.uy/anxml.aspx?58',
                'name': 'Montevideo Porta',
                'twitter': 'portalmvd'
            },
            {
                'url': 'https://ladiaria.com.uy/feeds/articulos/',
                'name': 'La diaria',
                'twitter': 'ladiaria'
            }
        ]
        rss = RSSParser(twitter_api, rss_sites)
        rss.parse_rss()
        logging.debug('Finished RSS')
    except Exception as e:
        logging.exception('RSS')
        print(e)

    logging.info('Finished script')


if __name__ == "__main__":
    main()

