from django.db import migrations, models
from django.db.models import Count, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce


def backfill_content_counters(apps, schema_editor):
    Content = apps.get_model('feed', 'Content')
    Reaction = apps.get_model('feed', 'Reaction')
    Comment = apps.get_model('feed', 'Comment')

    Content.objects.update(
        like_count=Coalesce(
            Subquery(
                Reaction.objects.filter(
                    content_id=OuterRef('pk'),
                    reaction='like',
                    is_active=True,
                ).values('content_id').annotate(c=Count('pk')).values('c')[:1]
            ),
            Value(0),
            output_field=IntegerField(),
        ),
        dislike_count=Coalesce(
            Subquery(
                Reaction.objects.filter(
                    content_id=OuterRef('pk'),
                    reaction='dislike',
                    is_active=True,
                ).values('content_id').annotate(c=Count('pk')).values('c')[:1]
            ),
            Value(0),
            output_field=IntegerField(),
        ),
        comment_count=Coalesce(
            Subquery(
                Comment.objects.filter(
                    content_id=OuterRef('pk'),
                ).values('content_id').annotate(c=Count('pk')).values('c')[:1]
            ),
            Value(0),
            output_field=IntegerField(),
        ),
    )


class Migration(migrations.Migration):

    dependencies = [
        ('feed', '0002_add_performance_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='content',
            name='like_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='content',
            name='dislike_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='content',
            name='comment_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(backfill_content_counters, migrations.RunPython.noop),
    ]
