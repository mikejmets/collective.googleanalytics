# -*- coding: utf-8 -*-
from AccessControl import ClassSecurityInfo
from App.class_init import InitializeClass
from OFS.ObjectManager import IFAwareObjectManager
from OFS.OrderedFolder import OrderedFolder
from Products.CMFPlone.PloneBaseTool import PloneBaseTool
from collective.googleanalytics import error
from collective.googleanalytics.config import GOOGLE_REQUEST_TIMEOUT
from collective.googleanalytics.config import SCOPES
from collective.googleanalytics.interfaces.report import IAnalyticsReport
from collective.googleanalytics.interfaces.utility import IAnalytics
from collective.googleanalytics.interfaces.utility import IAnalyticsSchema
from datetime import datetime
from plone import api
from plone.memoize import ram
from plone.registry.interfaces import IRegistry
from time import time
from zope.annotation.interfaces import IAttributeAnnotatable
from zope.component import getUtility
from zope.i18nmessageid import MessageFactory
from zope.interface import implementer
from zope.schema.fieldproperty import FieldProperty
from httplib import ResponseNotReady
from googleapiclient.http import HttpError

from apiclient.discovery import build

import json
import logging
import socket

from google.oauth2.service_account import Credentials

logger = logging.getLogger('collective.googleanalytics')

DEFAULT_TIMEOUT = socket.getdefaulttimeout()

_ = MessageFactory('collective.googleanalytics')


def account_feed_cachekey(func, instance, feed_path):
    """
    Cache key for the account feed. We only refresh it every ten minutes.
    """

    cache_interval = instance.cache_interval
    cache_interval = (cache_interval > 0 and cache_interval * 60) or 1
    return hash((time() // cache_interval, feed_path))


@implementer(IAnalytics, IAttributeAnnotatable)
class Analytics(PloneBaseTool, IFAwareObjectManager, OrderedFolder):
    """
    Analytics utility
    """

    security = ClassSecurityInfo()

    id = 'portal_analytics'
    meta_type = 'Google Analytics Tool'

    _product_interfaces = (IAnalyticsReport,)

    security.declarePrivate('email')
    security.declarePrivate('password')

    security.declarePrivate('tracking_web_property')
    tracking_web_property = FieldProperty(IAnalytics['tracking_web_property'])

    security.declarePrivate('tracking_plugin_names')
    tracking_plugin_names = FieldProperty(IAnalytics['tracking_plugin_names'])

    security.declarePrivate('tracking_excluded_roles')
    tracking_excluded_roles = FieldProperty(IAnalytics['tracking_excluded_roles'])

    security.declarePrivate('reports_profile')
    reports_profile = FieldProperty(IAnalytics['reports_profile'])

    security.declarePrivate('reports')
    reports = FieldProperty(IAnalytics['reports'])

    security.declarePrivate('cache_interval')
    cache_interval = FieldProperty(IAnalytics['cache_interval'])

    security.declarePrivate('report_categories')
    report_categories = FieldProperty(IAnalytics['report_categories'])

    security.declarePrivate('_v_temp_clients')
    _v_temp_clients = None

    security.declarePrivate('_ga_service')
    _ga_service = None

    security.declarePrivate('_getAuthenticatedClient')
    security.declarePrivate('is_auth')
    security.declarePrivate('makeClientRequest')
    security.declarePrivate('getReports')
    security.declarePrivate('getCategoriesChoices')
    security.declarePrivate('getAccountsFeed')

    def is_auth(self):
        return self.ga_service() is not None

    def ga_service(self):
        settings = self.get_settings()
        try: 
            client_credentials = json.loads(settings.service_account)
        except TypeError:
            logger.warn('Could not extract credentials from {0}'.format(settings.service_account))
            return None

        credentials = Credentials.from_service_account_info(
                client_credentials, scopes=SCOPES)
        try:
            service = build('analytics', 'v3', credentials=credentials)
        except ResponseNotReady:
            logger.warn('Could not connect. Not connected to the')
            return None
        return service

    def get_accounts(self):
        service = self.ga_service()
        try:
            accounts = service.management().accounts().list().execute()
        except HttpError:
            logger.warn('Could not authenticate!')
        return accounts




    def getReports(self, category=None):
        """
        List the available Analytics reports. If a category is specified, only
        reports of that category are returned. Otherwise, all reports are
        returned.
        """

        for obj in self.values():
            if IAnalyticsReport.providedBy(obj):
                if (category and category in obj.categories) or not category:
                    yield obj

    def getCategoriesChoices(self):
        """
        Return a list of possible report categories.
        """

        return self.report_categories

    @ram.cache(account_feed_cachekey)
    def getAccountsFeed(self, feed_path):
        """
        Returns the list of accounts.
        """
        feed = 'management/' + feed_path
        res = self.makeClientRequest(feed)
        return res

    def revoke_token(self):
        logger.debug("Trying to revoke token")
        try:
            oauth2_token = self._auth_token
            if oauth2_token:
                oauth2_token.revoke()
                logger.debug("Token revoked successfuly")
        except OAuth2RevokeError:
            # Authorization already revoked
            logger.debug("Token was already revoked")
            pass
        except socket.gaierror:
            logger.debug("There was a connection issue, could not revoke "
                         "token.")
            raise error.RequestTimedOutError, (
                'You may not have internet access. Please try again '
                'later.'
            )

        self._auth_token = None
        self._valid_token = False

    def get_settings(self):
        registry = getUtility(IRegistry)
        records = registry.forInterface(IAnalyticsSchema)
        return records

InitializeClass(Analytics)
