document.getElementById('submitButton').addEventListener('click', function() {
    const link = document.getElementById('linkInput').value;
    if (link) {
        showNotification("Подключаемся к сессиям...", "g.png");
        fetch('/submit', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ link: link })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showNotification(`Жалобы успешно были отправлены\nКол-во жалоб: ${data.count}`, "success.png");
            } else {
                showNotification("Ошибка при отправке жалобы", "wait.png");
            }
        });
    } else {
        alert("Пожалуйста, введите ссылку на нарушение.");
    }
});

function showNotification(message, image) {
    const notifications = document.getElementById('notifications');
    const notification = document.createElement('div');
    notification.className = 'notification';
    notification.innerHTML = `<img src="/static/images/${image}" alt="Notification" style="width: 20px; vertical-align: middle;"> ${message}`;
    notifications.appendChild(notification);
    setTimeout(() => {
        notifications.removeChild(notification);
    }, 5000);
}
