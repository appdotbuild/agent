import { GenericHandler } from "../common/handler";
{% for handler_name, handler in handlers.items() %}
import { {{ handler_name }} } from "../handlers/{{ handler.module }}";
{% endfor %}

export const handlers: {[key: string]: GenericHandler<any[], any>} = {
    {% for handler_name in handlers.keys() %}
    '{{ handler_name }}': {{ handler_name }},
    {% endfor %}
};