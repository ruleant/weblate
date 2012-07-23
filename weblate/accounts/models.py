from django.db import models
from django.dispatch import receiver
from django.contrib.auth.models import User
from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_save
from django.utils.translation import ugettext_lazy as _, gettext, ugettext_noop
from django.contrib import messages
from django.contrib.auth.models import Group, Permission, User
from django.db.models.signals import post_syncdb
from django.contrib.sites.models import Site
from django.utils import translation
from django.template.loader import render_to_string, get_template_from_string
from django.template.context import Context

from south.signals import post_migrate

from weblate.lang.models import Language
from weblate.trans.models import Project
import weblate

class ProfileManager(models.Manager):
    '''
    Manager providing shortcuts for subscription queries.
    '''
    def subscribed_any_translation(self, project):
        return self.filter(subscribe_any_translation = True, subscriptions = project)

    def subscribed_new_string(self, project):
        return self.filter(subscribe_new_string = True, subscriptions = project)

    def subscribed_new_suggestion(self, project):
        return self.filter(subscribe_new_suggestion = True, subscriptions = project)

    def subscribed_new_contributor(self, project):
        return self.filter(subscribe_new_contributor = True, subscriptions = project)

class Profile(models.Model):
    user = models.ForeignKey(User, unique = True, editable = False)
    language = models.CharField(
        verbose_name = _(u"Interface Language"),
        max_length = 10,
        choices = settings.LANGUAGES
    )
    languages = models.ManyToManyField(
        Language,
        verbose_name = _('Languages'),
        blank = True,
    )
    secondary_languages = models.ManyToManyField(
        Language,
        verbose_name = _('Secondary languages'),
        related_name = 'secondary_profile_set',
        blank = True,
    )
    suggested = models.IntegerField(default = 0, db_index = True)
    translated = models.IntegerField(default = 0, db_index = True)

    subscriptions = models.ManyToManyField(
        Project,
        verbose_name = _('Subscribed projects')
    )

    subscribe_any_translation = models.BooleanField(
        verbose_name = _('Notification on any translation'),
        default = False
    )
    subscribe_new_string = models.BooleanField(
        verbose_name = _('Notification on new string to translate'),
        default = False
    )
    subscribe_new_suggestion = models.BooleanField(
        verbose_name = _('Notification on new suggestion'),
        default = False
    )
    subscribe_new_contributor = models.BooleanField(
        verbose_name = _('Notification on new contributor'),
        default = False
    )

    objects = ProfileManager()

    def __unicode__(self):
        return self.user.username

    def notify_user(self, notification, translation, context = {}, headers = {}):
        '''
        Wrapper for sending notifications to user.
        '''
        cur_language = translation.get_language()
        try:
            # Load user languagesubject_fmt,
            translation.activate(self.language)

            # Template names
            subject_template = 'mail/%s_subject.txt' % notification
            body_template = 'mail/%s.txt' % notification

            # Adjust context
            context['translation'] = translation
            context['current_site'] = Site.objects.get_current()

            # Render subject
            subject = render_to_string(subject_template, context)

            # Render body
            body = render_to_string(body_template, context)

            # Define headers
            headers['Auto-Submitted'] = 'auto-generated'
            headers['X-AutoGenerated'] = 'yes'
            headers['Precedence'] = 'bulk'
            headers['X-Mailer'] = 'Weblate %s' % weblate.VERSION

            # Create message
            email = EmailMessage(
                settings.EMAIL_SUBJECT_PREFIX + subject,
                body,
                to = self.user.email,
                headers = headers
            )

            # Send it out
            email.send(fail_silently = False)
        finally:
            translation.activate(cur_language)
        return text

    def notify_any_translation(self, translation, unit):
        '''
        Sends notification on translation.
        '''
        self.notify_user(
            'any_translation',
            translation,
            {
                'unit': unit,
            }
        )

    def notify_new_string(self, translation):
        '''
        Sends notification on new strings to translate.
        '''
        self.notify_user(
            'new_string',
            translation,
        )

    def notify_new_suggestion(self, translation, suggestion):
        '''
        Sends notification on new suggestion.
        '''
        self.notify_user(
            'new_suggestion',
            translation,
            {
                'suggestion': suggestion,
            }
        )

    def notify_new_contributor(self, translation, user):
        '''
        Sends notification on new contributor.
        '''
        self.notify_user(
            'new_contributor',
            translation,
            {
                'user': user,
            }
        )

@receiver(user_logged_in)
def set_lang(sender, **kwargs):
    '''
    Signal handler for setting user language and
    migrating profile if needed.
    '''
    request = kwargs['request']
    user = kwargs['user']

    # Get or create profile
    try:
        profile = user.get_profile()
    except Profile.DoesNotExist:
        profile, newprofile = Profile.objects.get_or_create(user = user)
        if newprofile:
            messages.info(request, gettext('Your profile has been migrated, you might want to adjust preferences.'))

    # Set language for session based on preferences
    lang_code = user.get_profile().language
    request.session['django_language'] = lang_code

def create_profile_callback(sender, **kwargs):
    '''
    Automatically create profile when creating new user.
    '''
    if kwargs['created']:
        # Create profile
        profile, newprofile = Profile.objects.get_or_create(user = kwargs['instance'])
        if newprofile:
            profile.save

        # Add user to Users group if it exists
        try:
            group = Group.objects.get(name = 'Users')
            kwargs['instance'].groups.add(group)
        except Group.DoesNotExist:
            pass

post_save.connect(create_profile_callback, sender = User)


def create_groups(update, move):
    '''
    Creates standard groups and gives them permissions.
    '''
    group, created = Group.objects.get_or_create(name = 'Users')
    if created or update:
        group.permissions.add(
            Permission.objects.get(codename = 'upload_translation'),
            Permission.objects.get(codename = 'overwrite_translation'),
            Permission.objects.get(codename = 'save_translation'),
            Permission.objects.get(codename = 'accept_suggestion'),
            Permission.objects.get(codename = 'delete_suggestion'),
            Permission.objects.get(codename = 'ignore_check'),
            Permission.objects.get(codename = 'upload_dictionary'),
            Permission.objects.get(codename = 'add_dictionary'),
            Permission.objects.get(codename = 'change_dictionary'),
            Permission.objects.get(codename = 'delete_dictionary'),
        )
    group, created = Group.objects.get_or_create(name = 'Managers')
    if created or update:
        group.permissions.add(
            Permission.objects.get(codename = 'author_translation'),
            Permission.objects.get(codename = 'upload_translation'),
            Permission.objects.get(codename = 'overwrite_translation'),
            Permission.objects.get(codename = 'commit_translation'),
            Permission.objects.get(codename = 'update_translation'),
            Permission.objects.get(codename = 'push_translation'),
            Permission.objects.get(codename = 'automatic_translation'),
            Permission.objects.get(codename = 'save_translation'),
            Permission.objects.get(codename = 'accept_suggestion'),
            Permission.objects.get(codename = 'delete_suggestion'),
            Permission.objects.get(codename = 'ignore_check'),
            Permission.objects.get(codename = 'upload_dictionary'),
            Permission.objects.get(codename = 'add_dictionary'),
            Permission.objects.get(codename = 'change_dictionary'),
            Permission.objects.get(codename = 'delete_dictionary'),
            Permission.objects.get(codename = 'lock_translation'),
            Permission.objects.get(codename = 'reset_translation'),
        )
    if move:
        for u in User.objects.all():
            u.groups.add(group)

def sync_create_groups(sender, **kwargs):
    '''
    Create groups on syncdb.
    '''
    if ('app' in kwargs and kwargs['app'] == 'accounts') or (sender is not None and sender.__name__ == 'weblate.accounts.models'):
        create_groups(False, False)

post_syncdb.connect(sync_create_groups)
post_migrate.connect(sync_create_groups)
