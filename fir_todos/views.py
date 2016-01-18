import datetime

from django.dispatch import receiver
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST
from django.http import HttpResponse
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q

from incidents.views import is_incident_handler
from incidents.models import Incident, model_created

from fir_todos.models import TodoItem, TodoItemForm, TodoListTemplate


@require_POST
@login_required
@user_passes_test(is_incident_handler)
def create(request, incident_id):
	incident = get_object_or_404(Incident, pk=incident_id)

	form = TodoItemForm(request.POST)
	item = form.save(commit=False)
	item.incident = incident
	item.category = incident.category
	item.done = False
	item.save()

	return render(request, 'fir_todos/single.html', {'item': item})


@login_required
@user_passes_test(is_incident_handler)
def list(request, incident_id):
	incident = get_object_or_404(Incident, pk=incident_id)
	todos = incident.todoitem_set.all()
	form = TodoItemForm()

	return render(request, 'fir_todos/list.html',
		{'todos': todos, 'form': form, 'incident_id': incident_id})


@require_POST
@login_required
@user_passes_test(is_incident_handler)
def delete(request, todo_id):
	todo = get_object_or_404(TodoItem, pk=todo_id)
	todo.delete()

	return HttpResponse('')


@require_POST
@login_required
@user_passes_test(is_incident_handler)
def toggle_status(request, todo_id):
	todo = get_object_or_404(TodoItem, pk=todo_id)
	todo.done = not todo.done
	if todo.done:
		todo.done_time = datetime.datetime.now()
	todo.save()

	referer = request.META.get('HTTP_REFERER', None)
	dashboard = False
	if ('/incidents/' not in referer) and ('/events/' not in referer):
		dashboard = True

	return render(request, 'fir_todos/single.html', {'item': todo, 'dashboard': dashboard})


@login_required
@user_passes_test(is_incident_handler)
def dashboard(request):
	todos = TodoItem.objects.filter(business_line__name='CERT', incident__isnull=False, done=False)
	todos = todos.select_related('incident', 'category')
	todos = todos.order_by('-incident__date')

	page = request.GET.get('page', 1)
	todos_per_page = request.user.profile.incident_number
	p = Paginator(todos, todos_per_page)

	try:
		todos = p.page(page)
	except (PageNotAnInteger, EmptyPage):
		todos = p.page(1)

	return render(request, 'fir_todos/dashboard.html', {'todos': todos})


def get_todo_templates(category, detection, bl):
	results = []

	q = Q(category=category) | Q(category__isnull=True)
	q &= Q(detection=detection) | Q(detection__isnull=True)
	q &= Q(concerned_business_lines=bl) | Q(concerned_business_lines__isnull=True)

	results += TodoListTemplate.objects.filter(q)

	if bl.parent:
		results += get_todo_templates(category, detection, bl.parent)

	return results


def create_task(task, instance, bl=None):
	task.pk = None
	task.incident = instance
	task.category = instance.category

	if bl:
		task.business_line = bl

	task.save()


@receiver(model_created, sender=Incident)
def new_event(sender, instance, **kwargs):
	todos = dict()

	for bl in instance.concerned_business_lines.all():
		for template in get_todo_templates(instance.category, instance.detection, bl):
			for task in template.todolist.all():
				if task.id not in todos:
					todos[task.id] = {'task': task, 'bls': [bl]}
				else:
					todos[task.id]['bls'].append(bl)

	for task_id in todos:
		if todos[task_id]['task'].business_line is None:
			for bl in todos[task_id]['bls']:
				create_task(todos[task_id]['task'], instance, bl)
		else:
			create_task(todos[task_id]['task'], instance)
