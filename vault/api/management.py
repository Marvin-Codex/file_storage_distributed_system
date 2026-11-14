"""Custom authenticated management UI for users and departments."""

from typing import ClassVar

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db.models import ProtectedError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from ..models import StorageNode

User = get_user_model()


def _is_manager(request: HttpRequest) -> bool:
    return bool(request.user.is_authenticated and request.user.is_staff)


def _can_manage_user(actor, managed_user) -> bool:
    if managed_user.is_superuser and not actor.is_superuser:
        return False
    return not (
        managed_user.is_staff
        and managed_user != actor
        and not actor.is_superuser
    )


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ("name",)
        labels: ClassVar = {"name": "Department name"}
        help_texts: ClassVar = {"name": "Use a clear name such as Computing or Finance."}


class UserForm(forms.ModelForm):
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Required when creating a user; leave blank when editing.",
    )
    departments = forms.ModelMultipleChoiceField(
        queryset=Group.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    is_staff = forms.BooleanField(required=False, label="Staff access")

    class Meta:
        model = User
        fields = ("username", "email", "password", "departments", "is_staff")

    def __init__(self, *args, actor=None, instance=None, **kwargs):
        super().__init__(*args, instance=instance, **kwargs)
        self.actor = actor
        self.fields["departments"].queryset = Group.objects.order_by("name")
        if instance is not None:
            self.initial["departments"] = instance.groups.all()
            self.initial["is_staff"] = instance.is_staff
        if not actor or not actor.is_superuser:
            self.fields.pop("is_staff")

    def clean_username(self):
        username = self.cleaned_data["username"]
        existing = User.objects.filter(username__iexact=username)
        if self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise forms.ValidationError("That username is already in use.")
        return username

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.instance.pk and not password:
            raise forms.ValidationError("A password is required for new users.")
        return password

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("password")
        if password:
            user.set_password(password)
        if commit:
            user.save()
            self.save_m2m()
        return user


class StorageNodeForm(forms.ModelForm):
    data_dir = forms.CharField(
        required=False,
        initial=r".\data\node1",
        label="Node data directory",
        help_text=r"Local folder for blobs, such as .\data\node1.",
        widget=forms.TextInput(
            attrs={
                "placeholder": r".\data\node1",
                "autocomplete": "off",
            }
        ),
    )
    master_url = forms.URLField(
        initial="http://127.0.0.1:8000",
        label="Master URL",
        help_text="The URL of the LANVault master server.",
        error_messages={
            "required": "Enter the master server URL.",
            "invalid": "Use a complete URL, for example http://127.0.0.1:8000.",
        },
        widget=forms.URLInput(
            attrs={
                "placeholder": "http://127.0.0.1:8000",
                "autocomplete": "url",
            }
        ),
    )

    class Meta:
        model = StorageNode
        fields = ("name", "address", "capacity_bytes")
        labels: ClassVar = {
            "name": "Node name",
            "address": "Node address",
            "capacity_bytes": "Capacity in bytes",
        }
        help_texts: ClassVar = {
            "name": "A unique name such as node1.",
            "address": "The address the master will use to reach this node.",
            "capacity_bytes": "Example: 10737418240 for 10 GB.",
        }
        widgets: ClassVar = {
            "name": forms.TextInput(
                attrs={"placeholder": "node1", "autocomplete": "off"}
            ),
            "address": forms.URLInput(
                attrs={
                    "placeholder": "http://127.0.0.1:9001",
                    "autocomplete": "url",
                }
            ),
            "capacity_bytes": forms.NumberInput(
                attrs={
                    "placeholder": "10737418240",
                    "min": "1",
                    "step": "1",
                    "inputmode": "numeric",
                }
            ),
        }

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if StorageNode.objects.filter(name__iexact=name).exists():
            raise forms.ValidationError(
                "This node name is already registered. Choose a different name, "
                "such as node2."
            )
        return name

    def clean_address(self):
        address = self.cleaned_data["address"].rstrip("/")
        if ":" not in address.split("://", 1)[-1]:
            raise forms.ValidationError(
                "Include a port in the address, for example "
                "http://127.0.0.1:9001."
            )
        return address

    def clean_capacity_bytes(self):
        capacity = self.cleaned_data["capacity_bytes"]
        if capacity <= 0:
            raise forms.ValidationError(
                "Capacity must be greater than zero. For 10 GB, enter 10737418240."
            )
        return capacity

    def clean_data_dir(self):
        data_dir = self.cleaned_data["data_dir"].strip()
        if not data_dir:
            raise forms.ValidationError(
                r"Enter a folder path, such as .\data\node1."
            )
        return data_dir


def _node_commands(
    node: StorageNode,
    data_dir: str,
    master_url: str,
) -> dict[str, str]:
    common = (
        f'$env:ROLE="controller"; $env:NODE_NAME="{node.name}"; '
        f'$env:NODE_ADDRESS="{node.address}"; '
        f'$env:NODE_DATA_DIR="{data_dir}"; '
        f'$env:NODE_CAPACITY_BYTES="{node.capacity_bytes}"; '
        f'$env:MASTER_URL="{master_url.rstrip("/")}"; '
        '$env:CLUSTER_SECRET="<same value as the master>";'
    )
    return {
        "server": f"{common} python manage.py runserver {node.address.rsplit(':', 1)[-1]}",
        "heartbeat": f"{common} python manage.py run_heartbeat",
    }


def _management_context() -> dict:
    return {
        "departments": Group.objects.order_by("name").prefetch_related("user_set"),
        "users": User.objects.order_by("username").prefetch_related("groups"),
        "nodes": StorageNode.objects.order_by("name"),
    }


class ManagementView(View):
    """GET /manage/ — protected CRUD console."""

    def dispatch(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if not request.user.is_authenticated:
            return redirect(f"/login/?next={request.path}")
        if not _is_manager(request):
            return render(request, "vault/forbidden.html", status=403)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest) -> HttpResponse:
        return render(request, "vault/management.html", _management_context())


class NodeCreateView(ManagementView):
    def get(self, request: HttpRequest) -> HttpResponse:
        return render(
            request,
            "vault/node_form.html",
            {
                "form": StorageNodeForm(
                    initial={
                        "name": "node1",
                        "address": "http://127.0.0.1:9001",
                        "capacity_bytes": 10737418240,
                        "data_dir": r".\data\node1",
                        "master_url": "http://127.0.0.1:8000",
                    }
                )
            },
        )

    def post(self, request: HttpRequest) -> HttpResponse:
        form = StorageNodeForm(request.POST)
        if form.is_valid():
            node = form.save()
            return render(
                request,
                "vault/node_setup.html",
                {
                    "node": node,
                    "commands": _node_commands(
                        node,
                        form.cleaned_data["data_dir"],
                        form.cleaned_data["master_url"],
                    ),
                },
            )
        return render(request, "vault/node_form.html", {"form": form})


class DepartmentCreateView(ManagementView):
    def get(self, request: HttpRequest) -> HttpResponse:
        return render(request, "vault/department_form.html", {"form": DepartmentForm()})

    def post(self, request: HttpRequest) -> HttpResponse:
        form = DepartmentForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Department created.")
            return redirect("vault:management")
        return render(request, "vault/department_form.html", {"form": form})


class DepartmentUpdateView(ManagementView):
    def get_object(self, pk):
        return get_object_or_404(Group, pk=pk)

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        return render(
            request,
            "vault/department_form.html",
            {"form": DepartmentForm(instance=self.get_object(pk))},
        )

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        form = DepartmentForm(request.POST, instance=self.get_object(pk))
        if form.is_valid():
            form.save()
            messages.success(request, "Department updated.")
            return redirect("vault:management")
        return render(request, "vault/department_form.html", {"form": form})


class DepartmentDeleteView(ManagementView):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        department = get_object_or_404(Group, pk=pk)
        try:
            department.delete()
        except ProtectedError:
            messages.error(
                request,
                "This department still owns stored files and cannot be deleted.",
            )
        else:
            messages.success(request, "Department deleted.")
        return redirect("vault:management")


class UserCreateView(ManagementView):
    def get(self, request: HttpRequest) -> HttpResponse:
        return render(
            request,
            "vault/user_form.html",
            {"form": UserForm(actor=request.user), "is_create": True},
        )

    def post(self, request: HttpRequest) -> HttpResponse:
        form = UserForm(request.POST, actor=request.user)
        if form.is_valid():
            user = form.save()
            user.groups.set(form.cleaned_data["departments"])
            messages.success(request, "User created.")
            return redirect("vault:management")
        return render(request, "vault/user_form.html", {"form": form, "is_create": True})


class UserUpdateView(ManagementView):
    def get_object(self, pk):
        return get_object_or_404(User, pk=pk)

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        user = self.get_object(pk)
        if not _can_manage_user(request.user, user):
            return render(request, "vault/forbidden.html", status=403)
        return render(
            request,
            "vault/user_form.html",
            {"form": UserForm(actor=request.user, instance=user), "is_create": False, "managed_user": user},
        )

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        user = self.get_object(pk)
        if not _can_manage_user(request.user, user):
            return render(request, "vault/forbidden.html", status=403)
        form = UserForm(request.POST, actor=request.user, instance=user)
        if form.is_valid():
            user = form.save()
            user.groups.set(form.cleaned_data["departments"])
            messages.success(request, "User updated.")
            return redirect("vault:management")
        return render(
            request,
            "vault/user_form.html",
            {"form": form, "is_create": False, "managed_user": user},
        )


class UserDeleteView(ManagementView):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        user = get_object_or_404(User, pk=pk)
        if user == request.user or not _can_manage_user(request.user, user):
            return render(request, "vault/forbidden.html", status=403)
        try:
            user.delete()
        except ProtectedError:
            messages.error(request, "This user owns stored files and cannot be deleted.")
        else:
            messages.success(request, "User deleted.")
        return redirect("vault:management")
