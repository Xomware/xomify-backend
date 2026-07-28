import boto3
from botocore.exceptions import ClientError
from lambdas.common.constants import FROM_EMAIL, AWS_DEFAULT_REGION, XOMIFY_URL
from lambdas.common.logger import get_logger

from lambdas.common.release_radar_email_template import (
    generate_release_radar_email,
    generate_release_radar_email_plain_text
)

log = get_logger(__file__)

ses_client = boto3.client('ses', region_name=AWS_DEFAULT_REGION)


def send_wrapped_email(to_email: str, subject: str, html_body: str, text_body: str) -> bool:
    """
    Send a wrapped preview email using AWS SES.
    
    Args:
        to_email: Recipient email address
        subject: Email subject line
        html_body: HTML version of the email
        text_body: Plain text version of the email
    
    Returns:
        True if sent successfully, raises exception otherwise
    """
    try:
        log.info(f"Sending email to {to_email}...")
        
        response = ses_client.send_email(
            Source=FROM_EMAIL,
            Destination={
                'ToAddresses': [to_email]
            },
            Message={
                'Subject': {
                    'Data': subject,
                    'Charset': 'UTF-8'
                },
                'Body': {
                    'Text': {
                        'Data': text_body,
                        'Charset': 'UTF-8'
                    },
                    'Html': {
                        'Data': html_body,
                        'Charset': 'UTF-8'
                    }
                }
            },
            Tags=[
                {
                    'Name': 'email_type',
                    'Value': 'monthly_wrapped'
                }
            ]
        )
        
        message_id = response.get('MessageId', 'unknown')
        log.info(f"Email sent to {to_email}, MessageId: {message_id}")
        return True
        
    except ClientError as err:
        error_code = err.response['Error']['Code']
        error_message = err.response['Error']['Message']
        log.error(f"SES ClientError sending to {to_email}: {error_code} - {error_message}")
        raise Exception(f"SES Error: {error_code} - {error_message}") from err
    except Exception as err:
        log.error(f"Error sending email to {to_email}: {err}")
        raise Exception(f"Send Email Error: {err}") from err


## FAVORITES YEAR-END REMINDER EMAIL ##
def _favorites_reminder_html(user_name: str, year: int) -> str:
    greeting = f"Hey {user_name}," if user_name else "Hey,"
    return (
        "<html><body style=\"font-family:Arial,Helvetica,sans-serif;color:#1a1a1a;\">"
        f"<h2>Your {year} Favorites are waiting 🎧</h2>"
        f"<p>{greeting}</p>"
        f"<p>The year is wrapping up — time to lock in your {year} favorite "
        "songs, albums, and artists on Xomify. Rank them, revisit them, and "
        "watch how your taste evolves over time.</p>"
        f"<p><a href=\"{XOMIFY_URL}\" "
        "style=\"display:inline-block;padding:12px 20px;background:#1db954;"
        "color:#ffffff;text-decoration:none;border-radius:24px;\">"
        f"Set your {year} favorites</a></p>"
        "<p style=\"color:#888;font-size:12px;\">— Xomify</p>"
        "</body></html>"
    )


def _favorites_reminder_text(user_name: str, year: int) -> str:
    greeting = f"Hey {user_name}," if user_name else "Hey,"
    return (
        f"{greeting}\n\n"
        f"The year is wrapping up — time to set your {year} favorite songs, "
        f"albums, and artists on Xomify.\n\n"
        f"Set your {year} favorites: {XOMIFY_URL}\n\n"
        "— Xomify"
    )


def send_favorites_reminder_email(to_email: str, user_name: str, year: int) -> bool:
    """
    Send the year-end "set your favorites" reminder via AWS SES.

    Returns True on success. Raises on failure so the cron caller can count it
    as a failed email (and NOT write the idempotency marker).
    """
    try:
        subject = f"Set your {year} favorites"
        html_body = _favorites_reminder_html(user_name, year)
        text_body = _favorites_reminder_text(user_name, year)

        log.info(f"Sending favorites reminder to {to_email} for {year}...")
        response = ses_client.send_email(
            Source=FROM_EMAIL,
            Destination={'ToAddresses': [to_email]},
            Message={
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {
                    'Text': {'Data': text_body, 'Charset': 'UTF-8'},
                    'Html': {'Data': html_body, 'Charset': 'UTF-8'},
                },
            },
            Tags=[
                {'Name': 'email_type', 'Value': 'favorites_reminder'},
                {'Name': 'year', 'Value': str(year)},
            ],
        )
        message_id = response.get('MessageId', 'unknown')
        log.info(f"Favorites reminder sent to {to_email}, MessageId: {message_id}")
        return True

    except ClientError as err:
        error_code = err.response['Error']['Code']
        error_message = err.response['Error']['Message']
        log.error(f"SES ClientError sending favorites reminder to {to_email}: {error_code} - {error_message}")
        raise Exception(f"SES Error: {error_code} - {error_message}") from err
    except Exception as err:
        log.error(f"Error sending favorites reminder to {to_email}: {err}")
        raise Exception(f"Send Favorites Reminder Error: {err}") from err


def verify_email_address(email: str) -> bool:
    """
    Send verification email to an address (for sandbox mode testing).
    """
    try:
        response = ses_client.verify_email_identity(EmailAddress=email)
        log.info(f"Verification email sent to {email}")
        return True
    except Exception as err:
        log.error(f"Error verifying email {email}: {err}")
        return False


def get_send_quota() -> dict:
    """
    Get current SES sending quota and usage.
    """
    try:
        response = ses_client.get_send_quota()
        return {
            'max_24_hour_send': response['Max24HourSend'],
            'max_send_rate': response['MaxSendRate'],
            'sent_last_24_hours': response['SentLast24Hours']
        }
    except Exception as err:
        log.error(f"Error getting send quota: {err}")
        return {}
    
## RELEASE RADAR EMAIL ##
def send_release_radar_email(
    to_email: str,
    user_name: str,
    week_key: str,
    stats: dict,
    releases: list,
    playlist_url: str
) -> bool:
    """
    Send a single release radar email.
    
    Args:
        to_email: Recipient email address
        user_name: User's display name
        week_key: Week key for display
        stats: Release statistics
        releases: List of releases for preview
        playlist_url: URL to the playlist
        
    Returns:
        True if sent successfully, False otherwise
    """
    try:
        # Generate email content
        html_body = generate_release_radar_email(
            user_name=user_name,
            week_key=week_key,
            stats=stats,
            releases=releases,
            playlist_url=playlist_url
        )
        
        text_body = generate_release_radar_email_plain_text(
            user_name=user_name,
            week_key=week_key,
            stats=stats,
            releases=releases,
            playlist_url=playlist_url
        )
        
        # Build subject line
        release_count = stats.get('releaseCount', 0)
        subject = f"📻 {release_count} new releases from artists you follow!"
        
        # Send via SES
        response = ses_client.send_email(
            Source=FROM_EMAIL,
            Destination={
                'ToAddresses': [to_email]
            },
            Message={
                'Subject': {
                    'Data': subject,
                    'Charset': 'UTF-8'
                },
                'Body': {
                    'Text': {
                        'Data': text_body,
                        'Charset': 'UTF-8'
                    },
                    'Html': {
                        'Data': html_body,
                        'Charset': 'UTF-8'
                    }
                }
            },
            Tags=[
                {'Name': 'EmailType', 'Value': 'ReleaseRadar'},
                {'Name': 'WeekKey', 'Value': week_key}
            ]
        )
        
        message_id = response.get('MessageId')
        log.info(f"Email sent to {to_email}, MessageId: {message_id}")
        return True
        
    except ClientError as err:
        error_code = err.response['Error']['Code']
        error_msg = err.response['Error']['Message']
        log.error(f"SES error sending to {to_email}: {error_code} - {error_msg}")
        return False
        
    except Exception as err:
        log.error(f"Error sending email to {to_email}: {err}")
        return False
