# coding: utf-8

import datetime
import simplejson as json
from cached_property import cached_property
from time import time
from enum import Enum

from app import db
from util import elapsed

class JiscDefaultPrices(Enum):
    TaylorFrancis = 954.10
    Sage = 659.99
    Wiley = 1350.47
    SpringerNature = 1476.53
    Elsevier = 3775

class JournalsDBRaw(db.Model):
    __tablename__ = "journalsdb_raw"
    issn_l = db.Column(db.Text, primary_key=True)
    issns = db.Column(db.Text)
    title = db.Column(db.Text)
    publisher = db.Column(db.Text)
    subscription_pricing = db.Column(db.Text)
    apc_pricing = db.Column(db.Text)

    def __repr__(self):
        return "<{} ({}) '{}' {}>".format(self.__class__.__name__, self.issn_l, self.title, self.publisher)

class JournalsDB(db.Model):
    __tablename__ = "journalsdb_computed"
    issn_l = db.Column(db.Text, primary_key=True)
    issns_string = db.Column(db.Text)
    title = db.Column(db.Text)
    publisher = db.Column(db.Text)
    subscription_price_usd = db.Column(db.Numeric(asdecimal=False))
    subscription_price_gbp = db.Column(db.Numeric(asdecimal=False))
    apc_price_usd = db.Column(db.Numeric(asdecimal=False))
    apc_price_gbp = db.Column(db.Numeric(asdecimal=False))

    def __init__(self, journal_raw):
        self.created = datetime.datetime.utcnow().isoformat()
        for attr in ("issn_l", "title", "publisher"):
            setattr(self, attr, getattr(journal_raw, attr))
        self.set_subscription_prices(journal_raw)
        self.set_apc_prices(journal_raw)
        super(JournalsDB, self).__init__()

    @cached_property
    def issns(self):
        return json.loads(self.issns_string)

    def set_subscription_prices(self, journal_raw):
        if journal_raw.subscription_pricing:
            subscription_dict = json.loads(journal_raw.subscription_pricing)
            for price_dict in subscription_dict["prices"]:
                if price_dict["currency"] == "USD":
                    self.subscription_price_usd = float(price_dict["price"])
                if price_dict["currency"] == "GBP":
                    self.subscription_price_gbp = float(price_dict["price"])

    def set_apc_prices(self, journal_raw):
        if journal_raw.apc_pricing:
            apc_dict = json.loads(journal_raw.apc_pricing)
            for price_dict in apc_dict["apc_prices"]:
                if price_dict["currency"] == "USD":
                    self.apc_price_usd = float(price_dict["price"])
                if price_dict["currency"] == "GBP":
                    self.apc_price_gbp = float(price_dict["price"])

    def get_subscription_price(self, currency="USD", use_high_price_if_unknown=False):
        response = None
        if currency == "USD":
            if self.subscription_price_usd:
                response = float(self.subscription_price_usd)
        elif currency == "GBP":
            if self.subscription_price_gbp:
                response = float(self.subscription_price_gbp)

        if not response:
            if use_high_price_if_unknown and currency == "GBP":
                JISC_DEFAULT_PRICE_IN_GBP = JiscDefaultPrices[self.publisher_code].value
                response = JISC_DEFAULT_PRICE_IN_GBP
        return response

    def get_apc_price(self, currency="USD"):
        response = None
        if currency == "USD":
            if self.apc_price_usd:
                response = float(self.apc_price_usd)
        elif currency == "GBP":
            if self.apc_price_gbp:
                response = float(self.apc_price_gbp)
        return response

    def __repr__(self):
        return "<{} ({}) '{}' {}>".format(self.__class__.__name__, self.issn_l, self.title, self.publisher)

print("loading journalsdb pricing metadata...", end=' ')
start_time = time()
jdb_pricing_list = JournalsDB.query.all()
[db.session.expunge(x) for x in jdb_pricing_list]
jdb_pricing = dict(list(zip([w.issn_l for w in jdb_pricing_list], jdb_pricing_list)))
print("loaded journalsdb pricing in {} seconds.".format(elapsed(start_time)))