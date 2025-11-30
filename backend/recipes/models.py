from django.db import models

# Create your models here.


class Recipe(models.Model):
    name = models.CharField(max_length=200)
    serves = models.IntegerField()
    ingredients = models.TextField()         # "chicken, pasta, garlic"
    instructions = models.TextField()        # method to cook

    def __str__(self):
        return self.name
    
